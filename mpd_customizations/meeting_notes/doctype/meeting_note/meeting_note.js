// ─────────────────────────────────────────────────────────────────────────────
// Meeting Note — frontend controller
// Sections:
//   1. form_refresh entry point
//   2. Recording state machine (audio capture only — no live transcription)
//   3. Extract Actions handler
//   4. Review dialog
//   5. Private helpers
// ─────────────────────────────────────────────────────────────────────────────

frappe.ui.form.on("Meeting Note", {

    // ─────────────────────────────────────────────────────────────────────────
    // 1. FORM REFRESH
    // ─────────────────────────────────────────────────────────────────────────

    refresh(frm) {
        _initMeetingState(frm);
        _renderButtons(frm);

        if (frm.doc.status === "Transcribing" || frm.doc.status === "Processing") {
            _startPolling(frm);
        }

        if (frm.doc.project) {
            _loadTaskTable(frm);
        }
    },

    onload(frm) {
        _initMeetingState(frm);
    },

    project(frm) {
        if (frm.doc.project) {
            _loadTaskTable(frm);
        } else {
            frm.get_field("project_tasks_html").$wrapper.html("");
        }
    },
});


// ─────────────────────────────────────────────────────────────────────────────
// 2. RECORDING STATE MACHINE
// Captures raw audio only. Transcription + diarization happens server-side
// when the user clicks "Extract Actions".
// ─────────────────────────────────────────────────────────────────────────────

function _initMeetingState(frm) {
    if (frm._meetingState) return;
    frm._meetingState = {
        isRecording: false,
        audioChunks: [],
        mediaRecorder: null,
        pollingTimer: null,
    };
}

async function _startRecording(frm) {
    const state = frm._meetingState;
    if (state.isRecording) return;

    // Save the doc first so audio upload has a valid docname to attach to
    if (frm.is_new() || frm.is_dirty()) {
        try {
            await frm.save();
        } catch (e) {
            frappe.msgprint({ title: __("Save Failed"), message: __("Please fill all required fields before recording."), indicator: "red" });
            return;
        }
    }

    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
        frappe.msgprint({ title: __("Microphone Error"), message: e.message, indicator: "red" });
        return;
    }

    state.audioChunks = [];
    const mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm", audioBitsPerSecond: 16000 });
    state.mediaRecorder = mediaRecorder;

    mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) state.audioChunks.push(e.data);
    };
    mediaRecorder.start(1000);

    state.isRecording = true;
    // Auto-stop after 55 minutes
    state.autoStopTimer = setTimeout(() => {
        frappe.show_alert({ message: __("Recording stopped automatically after 55 minutes."), indicator: "orange" });
        _stopRecording(frm);
    }, 55 * 60 * 1000);

    _setRecordingIndicator(frm, true);
    _renderButtons(frm);
}

async function _stopRecording(frm) {
    const state = frm._meetingState;
    if (!state.isRecording) return;

    state.mediaRecorder.stop();
    state.mediaRecorder.stream.getTracks().forEach(t => t.stop());
    state.isRecording = false;
    if (state.autoStopTimer) { clearTimeout(state.autoStopTimer); state.autoStopTimer = null; }

    _setRecordingIndicator(frm, false);
    await _uploadAudio(frm);
    _renderButtons(frm);
}

async function _uploadAudio(frm) {
    const state = frm._meetingState;
    if (!state.audioChunks.length) return;

    const blob = new Blob(state.audioChunks, { type: "audio/webm" });
    const filename = `meeting-${frm.doc.name}-${Date.now()}.webm`;
    const file = new File([blob], filename, { type: "audio/webm" });

    const formData = new FormData();
    formData.append("file", file, filename);
    formData.append("doctype", "Meeting Note");
    formData.append("docname", frm.doc.name);
    formData.append("fieldname", "audio_file");
    formData.append("is_private", "1");

    frappe.show_alert({ message: __("Uploading audio…"), indicator: "blue" });

    try {
        const res = await fetch("/api/method/upload_file", {
            method: "POST",
            headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
            body: formData,
        });
        const data = await res.json();
        if (data.message && data.message.file_url) {
            frm.set_value("audio_file", data.message.file_url);
            await frm.save();
            frappe.show_alert({ message: __("Audio saved."), indicator: "green" });
            _renderButtons(frm);
        }
    } catch (err) {
        console.warn("Audio upload failed:", err);
        frappe.show_alert({ message: __("Audio upload failed."), indicator: "red" });
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// 3. TRANSCRIBE + EXTRACT ACTIONS HANDLERS
// ─────────────────────────────────────────────────────────────────────────────

function _transcribeAudio(frm) {
    frappe.confirm(
        __("Transcribe the audio with speaker diarization? This may take a few minutes."),
        async () => {
            try {
                await frm.call("start_transcription");
                frappe.show_alert({
                    message: __("Transcription started. Page will update when complete."),
                    indicator: "blue",
                });
                await frm.reload_doc();
                _startPolling(frm);
            } catch (e) {
                frappe.msgprint({ title: __("Error"), message: e.message, indicator: "red" });
            }
        }
    );
}

function _extractActions(frm) {
    frappe.confirm(
        __("Extract action items from the transcript using AI? Tasks will be created for review."),
        async () => {
            try {
                await frm.call("start_extraction");
                frappe.show_alert({
                    message: __("Extraction started. Page will update automatically when complete."),
                    indicator: "blue",
                });
                await frm.reload_doc();
                _startPolling(frm);
            } catch (e) {
                frappe.msgprint({ title: __("Error"), message: e.message, indicator: "red" });
            }
        }
    );
}

function _startPolling(frm) {
    const state = frm._meetingState;
    if (state.pollingTimer) return;

    const msg = frm.doc.status === "Transcribing"
        ? __("Transcribing audio with speaker diarization…")
        : __("Extracting action items…");
    const indicator = frm.page.add_inner_message(
        `<span class="text-muted"><i class="fa fa-spinner fa-spin"></i> ${msg}</span>`
    );

    state.pollingTimer = setInterval(async () => {
        try {
            const r = await frappe.call({
                method: "frappe.client.get_value",
                args: { doctype: "Meeting Note", fieldname: "status", filters: { name: frm.docname } },
            });
            const status = r.message && r.message.status;
            if (status && status !== "Transcribing" && status !== "Processing") {
                clearInterval(state.pollingTimer);
                state.pollingTimer = null;
                if (indicator && indicator.remove) indicator.remove();
                await frm.reload_doc();
            }
        } catch (e) { /* ignore transient errors */ }
    }, 10000);
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. REVIEW DIALOG
// ─────────────────────────────────────────────────────────────────────────────

async function _openReviewDialog(frm) {
    let tasks;
    try {
        const r = await frm.call("get_pending_tasks");
        tasks = r.message || [];
    } catch (e) {
        frappe.msgprint({ title: __("Error"), message: e.message, indicator: "red" });
        return;
    }

    if (!tasks.length) {
        frappe.msgprint({ title: __("No Pending Actions"), message: __("No new tasks are pending review. Existing task updates were applied directly."), indicator: "blue" });
        return;
    }

    // Choice dialog: approve all vs review each
    const taskListHtml = tasks.map((t) =>
        `<tr>
            <td style="font-family:monospace;font-size:11px">
                <a href="/app/task/${t.name}" target="_blank">${t.name}</a>
            </td>
            <td>${frappe.utils.escape_html(t.subject)}</td>
            <td>${t.priority || "Medium"}</td>
            <td>${t.suggested_assignee || "<span class='text-muted'>Unassigned</span>"}</td>
        </tr>`
    ).join("");

    const choiceDialog = new frappe.ui.Dialog({
        title: __("{0} New Task(s) Pending Review", [tasks.length]),
        fields: [
            {
                fieldtype: "HTML",
                options: `
                    <p class="text-muted small">The AI created these new tasks. Existing task updates (comments, due dates, objectives) were applied directly.</p>
                    <table class="table table-bordered table-condensed" style="font-size:12px">
                        <thead style="background:#f7f7f7">
                            <tr><th>Task</th><th>Subject</th><th>Priority</th><th>Assignee</th></tr>
                        </thead>
                        <tbody>${taskListHtml}</tbody>
                    </table>`,
            },
        ],
        primary_action_label: __("Approve All"),
        primary_action: async () => {
            choiceDialog.hide();
            await _submitReview(frm, tasks, null);
        },
        secondary_action_label: __("Review Each"),
        secondary_action: () => {
            choiceDialog.hide();
            _openDetailedReview(frm, tasks);
        },
    });

    choiceDialog.show();
}

function _openDetailedReview(frm, tasks) {
    const fields = [];
    tasks.forEach((task, idx) => {
        if (idx > 0) fields.push({ fieldtype: "Section Break" });
        fields.push(
            {
                fieldtype: "HTML",
                options: `<div class="text-muted small mb-2">
                    Task ${idx + 1}
                    <a href="/app/task/${task.name}" target="_blank" style="font-family:monospace;font-size:11px;margin-left:6px">${task.name}</a>
                    ${task.parent_task ? `<span class="badge badge-secondary ml-1">subtask of ${task.parent_task}</span>` : ""}
                </div>`,
            },
            {
                label: __("Subject"),
                fieldname: `subject_${task.name}`,
                fieldtype: "Data",
                default: task.subject,
                reqd: 1,
            },
            { fieldtype: "Column Break" },
            {
                label: __("Priority"),
                fieldname: `priority_${task.name}`,
                fieldtype: "Select",
                options: "Urgent\nHigh\nMedium\nLow",
                default: task.priority || "Medium",
            },
            {
                label: __("Assignee"),
                fieldname: `assignee_${task.name}`,
                fieldtype: "Link",
                options: "User",
                default: task.suggested_assignee || "",
            },
            {
                label: __("Approve"),
                fieldname: `approve_${task.name}`,
                fieldtype: "Check",
                default: 1,
            },
            { fieldtype: "Section Break" },
            {
                label: __("Description"),
                fieldname: `desc_${task.name}`,
                fieldtype: "Small Text",
                default: task.description || "",
                read_only: 1,
            }
        );
    });

    const dialog = new frappe.ui.Dialog({
        title: __("Review Each Task"),
        size: "large",
        fields,
        primary_action_label: __("Confirm"),
        primary_action: async (values) => {
            dialog.hide();
            await _submitReview(frm, tasks, values);
        },
    });

    dialog.show();
}

async function _submitReview(frm, tasks, values) {
    // values is null when "Approve All" is chosen
    const allActions = tasks.map(task => ({
        task_name: task.name,
        assignee: values ? (values[`assignee_${task.name}`] || null) : null,
        action: values ? (values[`approve_${task.name}`] ? "approve" : "reject") : "approve",
    }));

    try {
        const r = await frm.call("bulk_approve", { approvals: allActions });
        const result = r.message || {};
        if (result.errors && result.errors.length) {
            frappe.msgprint({
                title: __("Some tasks failed"),
                message: result.errors.map(e => `${e.task}: ${e.error}`).join("<br>"),
                indicator: "red",
            });
        } else {
            frappe.show_alert({
                message: __("{0} approved, {1} rejected.", [result.approved || 0, result.rejected || 0]),
                indicator: "green",
            });
        }
        frm.reload_doc();
    } catch (e) {
        frappe.msgprint({ title: __("Error"), message: e.message, indicator: "red" });
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// 5. PRIVATE HELPERS
// ─────────────────────────────────────────────────────────────────────────────

function _renderButtons(frm) {
    frm.clear_custom_buttons();

    const state = frm._meetingState;
    const status = frm.doc.status;

    if (status === "Draft") {
        if (state.isRecording) {
            frm.add_custom_button(
                `<span style="color:#e74c3c">&#9632; ${__("Stop Recording")}</span>`,
                () => _stopRecording(frm)
            );
        } else {
            frm.add_custom_button(
                `&#9679; ${__("Start Recording")}`,
                () => _startRecording(frm)
            );
        }

        if (frm.doc.audio_file && !state.isRecording) {
            const label = frm.doc.transcript ? __("Re-transcribe Audio") : __("Transcribe Audio");
            frm.add_custom_button(label, () => _transcribeAudio(frm), __("Actions"));
        }

        if (frm.doc.transcript && !state.isRecording) {
            frm.add_custom_button(__("Extract Actions"), () => _extractActions(frm), __("Actions"));
        }
    }

    if (status === "Review") {
        frm.add_custom_button(__("Review Actions"), () => _openReviewDialog(frm), __("Actions"));
    }
}

async function _loadTaskTable(frm) {
    const wrapper = frm.get_field("project_tasks_html").$wrapper;
    wrapper.html(`<p class="text-muted small">Loading tasks…</p>`);

    let tasks = [];
    try {
        const r = await frm.call("get_project_tasks");
        tasks = r.message || [];
    } catch (e) {
        wrapper.html(`<p class="text-muted small">Could not load tasks.</p>`);
        return;
    }

    const now = new Date();
    const statusColour = { Open: "#3498db", Working: "#e67e22", "Pending Review": "#9b59b6", Completed: "#27ae60", Cancelled: "#95a5a6" };
    const priorityColour = { Urgent: "#e74c3c", High: "#e67e22", Medium: "#3498db", Low: "#95a5a6" };

    const rows = tasks.length ? tasks.map(t => {
        const due = t.exp_end_date
            ? `<span style="color:${new Date(t.exp_end_date) < now ? "#e74c3c" : "inherit"}">${t.exp_end_date}</span>`
            : `<span class="text-muted">—</span>`;
        const assignee = t.assigned_to
            ? `<span title="${t.assigned_to}">${t.assigned_to.split("@")[0]}</span>`
            : `<span class="text-muted">—</span>`;
        const dot = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${priorityColour[t.priority] || "#ccc"};margin-right:4px;vertical-align:middle"></span>`;
        const statusBg = statusColour[t.status] || "#ccc";
        return `<tr>
            <td><a href="/app/task/${t.name}" target="_blank" style="font-family:monospace;font-size:11px">${t.name}</a></td>
            <td><a href="/app/task/${t.name}" target="_blank">${frappe.utils.escape_html(t.subject)}</a></td>
            <td>${dot}${t.priority || "—"}</td>
            <td>${assignee}</td>
            <td>${due}</td>
            <td><span style="display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;background:${statusBg};color:#fff">${t.status}</span></td>
        </tr>`;
    }).join("") : `<tr><td colspan="6" class="text-muted text-center">No open tasks.</td></tr>`;

    wrapper.html(`
        <table class="table table-bordered table-condensed" style="font-size:12px;margin-bottom:0">
            <thead style="background:#f7f7f7">
                <tr>
                    <th>Task</th><th>Subject</th><th>Priority</th>
                    <th>Assignee</th><th>Due Date</th><th>Status</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `);
}


function _setRecordingIndicator(frm, isRecording) {
    frm.layout.wrapper.find(".recording-indicator").remove();

    if (isRecording) {
        const indicator = $(`
            <div class="recording-indicator alert alert-danger d-flex align-items-center" style="margin: 8px 0;">
                <span style="width:10px;height:10px;border-radius:50%;background:#e74c3c;
                             display:inline-block;margin-right:8px;
                             animation:blink 1s step-start infinite;"></span>
                <strong>${__("Recording in progress…")}</strong>
            </div>
            <style>@keyframes blink { 50% { opacity: 0; } }</style>
        `);
        frm.layout.wrapper.find("[data-fieldname='section_recording']").after(indicator);
    }
}
