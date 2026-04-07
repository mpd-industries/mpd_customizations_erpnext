import json
import time
from importlib import import_module

import frappe
import litellm
from litellm import completion
from pydantic import BaseModel

from mpd_customizations.ai.parser import normalise_parsed, parse_response

litellm.drop_params = True
litellm.suppress_debug_info = True


class AIGateway:

	def __init__(self, task_key: str):
		self.task_key = task_key
		self.task = self._load_task(task_key)
		self.provider = frappe.get_doc(
			"LLM Provider", self.task.provider
		)

	def _load_task(self, task_key):
		name = frappe.db.get_value(
			"LLM Task",
			{"task_key": task_key, "enabled": 1},
			"name",
		)
		if not name:
			frappe.throw(
				f"No enabled LLM Task found for key: {task_key}"
			)
		return frappe.get_doc("LLM Task", name)

	@property
	def system_prompt(self) -> str:
		if self.task.system_prompt and self.task.system_prompt.strip():
			return self.task.system_prompt
		try:
			mod = import_module(
				f"mpd_customizations.ai.prompts.{self.task_key}"
			)
			return mod.SYSTEM_PROMPT
		except (ImportError, AttributeError):
			frappe.throw(
				f"No prompt found for task '{self.task_key}'. "
				f"Add one in LLM Task."
			)

	def _get_response_format(self):
		try:
			mod = import_module(
				f"mpd_customizations.ai.prompts.{self.task_key}"
			)
			if hasattr(mod, "get_response_format"):
				return mod.get_response_format()
		except ImportError:
			pass
		return {"type": "json_object"}

	def _parse_content(self, raw: str) -> dict:
		text = (raw or "").strip()
		fmt = self._get_response_format()
		if isinstance(fmt, type) and issubclass(fmt, BaseModel):
			try:
				obj = fmt.model_validate_json(text)
				return normalise_parsed(obj.model_dump())
			except Exception:
				pass
		return parse_response(raw)

	def _completion_messages(self, user_prompt: str):
		return [
			{
				"role": "system",
				"content": self.system_prompt,
			},
			{
				"role": "user",
				"content": user_prompt,
			},
		]

	def _call_litellm(self, user_prompt: str, api_key, api_base):
		messages = self._completion_messages(user_prompt)
		common = dict(
			model=self.task.model_string,
			messages=messages,
			max_tokens=self.task.max_tokens or 1500,
			temperature=self.task.temperature or 0.1,
			api_key=api_key,
			api_base=api_base,
			drop_params=False,
		)
		fmt = self._get_response_format()
		if isinstance(fmt, type) and issubclass(fmt, BaseModel):
			try:
				return completion(
					response_format=fmt,
					**common,
				)
			except Exception as e:
				frappe.log_error(
					f"AIGateway {self.task_key} structured output",
					str(e),
				)
				return completion(
					response_format={"type": "json_object"},
					**common,
				)
		rf = fmt if isinstance(fmt, dict) else {"type": "json_object"}
		return completion(response_format=rf, **common)

	def run(
		self,
		user_prompt: str,
		doc_type: str,
		doc_name: str,
	) -> dict:
		if not self.provider.enabled:
			return self._error("Provider is disabled")

		api_base = (self.provider.api_base_url or "").strip() or None

		api_key = self.provider.get_password("api_key")
		start = time.time()

		try:
			resp = self._call_litellm(user_prompt, api_key, api_base)
			elapsed = int((time.time() - start) * 1000)
			raw = resp.choices[0].message.content

			parsed = self._parse_content(raw)

			threshold = self.task.confidence_threshold or 75
			if (
				parsed["decision"] == "Approved"
				and parsed["confidence"] < threshold
			):
				parsed["decision"] = "Flagged"
				parsed["issues"].append(
					f"Confidence {parsed['confidence']} "
					f"below threshold {threshold}"
				)

			self._log(
				doc_type,
				doc_name,
				parsed,
				raw,
				resp.usage,
				elapsed,
			)
			return parsed

		except litellm.RateLimitError:
			return self._try_fallback(
				user_prompt, doc_type, doc_name, "Rate limit"
			)
		except Exception as e:
			frappe.log_error(
				f"AIGateway {self.task_key}", str(e)
			)
			return self._try_fallback(
				user_prompt, doc_type, doc_name, str(e)
			)

	def _try_fallback(
		self, user_prompt, doc_type, doc_name, reason
	) -> dict:
		if self.task.fallback_task:
			fallback_key = frappe.db.get_value(
				"LLM Task",
				self.task.fallback_task,
				"task_key",
			)
			frappe.log_error(
				f"AIGateway fallback: {self.task_key}",
				f"{reason} → {fallback_key}",
			)
			return AIGateway(fallback_key).run(
				user_prompt, doc_type, doc_name
			)
		return self._error(reason)

	def _error(self, reason: str) -> dict:
		return {
			"decision": "Flagged",
			"confidence": 0,
			"brief": (
				f"AI review unavailable ({reason}). "
				"Routed to Master Approver."
			),
			"issues": [f"AI error: {reason}"],
			"checks": {},
		}

	def _log(
		self,
		doc_type,
		doc_name,
		parsed,
		raw,
		usage,
		elapsed,
	):
		try:
			frappe.get_doc({
				"doctype": "LLM Review Log",
				"document_type": doc_type,
				"document_name": doc_name,
				"task_key": self.task_key,
				"model_used": self.task.model_string,
				"decision": parsed["decision"],
				"confidence_score": parsed["confidence"],
				"brief": parsed["brief"],
				"issues": json.dumps(
					parsed.get("issues", [])
				),
				"prompt_tokens": getattr(
					usage, "prompt_tokens", 0
				),
				"completion_tokens": getattr(
					usage, "completion_tokens", 0
				),
				"cost_usd": self._cost(usage),
				"response_time_ms": elapsed,
				"raw_response": raw,
				"prompt_version": self.task.prompt_version or 1,
			}).insert(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			pass

	def _cost(self, usage) -> float:
		try:
			info = litellm.get_model_info(self.task.model_string)
			return round(
				getattr(usage, "prompt_tokens", 0)
				* info.get("input_cost_per_token", 0)
				+ getattr(usage, "completion_tokens", 0)
				* info.get("output_cost_per_token", 0),
				6,
			)
		except Exception:
			return 0.0
