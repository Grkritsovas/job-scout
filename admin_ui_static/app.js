const state = {
  profiles: [],
  selectedProfileId: "",
  versions: [],
  currentProfile: null,
};

const els = {
  backendLabel: document.getElementById("backendLabel"),
  profileCount: document.getElementById("profileCount"),
  profileList: document.getElementById("profileList"),
  profileForm: document.getElementById("profileForm"),
  profileEditor: document.getElementById("profileEditor"),
  profileStatus: document.getElementById("profileStatus"),
  selectedProfileTitle: document.getElementById("selectedProfileTitle"),
  selectedProfileMeta: document.getElementById("selectedProfileMeta"),
  profileVersionSelect: document.getElementById("profileVersionSelect"),
  versionPreview: document.getElementById("versionPreview"),
  versionPanel: document.getElementById("versionPanel"),
  auditCount: document.getElementById("auditCount"),
  auditRecipient: document.getElementById("auditRecipient"),
  auditFamily: document.getElementById("auditFamily"),
  auditClassification: document.getElementById("auditClassification"),
  auditRun: document.getElementById("auditRun"),
  auditLimit: document.getElementById("auditLimit"),
  auditSort: document.getElementById("auditSort"),
  auditSummary: document.getElementById("auditSummary"),
  auditRows: document.getElementById("auditRows"),
};

document.querySelectorAll(".nav-tab").forEach((button) => {
  button.addEventListener("click", () => {
    switchView(button.dataset.view);
    if (button.dataset.view === "auditView") {
      refreshAudit();
    }
  });
});

document.getElementById("newProfileButton").addEventListener("click", newProfile);
document.getElementById("reloadProfilesButton").addEventListener("click", loadProfiles);
document.getElementById("validateProfileButton").addEventListener("click", validateProfile);
document.getElementById("normalizeProfileButton").addEventListener("click", normalizeProfile);
document.getElementById("saveProfileButton").addEventListener("click", saveProfile);
document.getElementById("loadVersionButton").addEventListener("click", compareSelectedVersion);
document.getElementById("restoreVersionButton").addEventListener("click", restoreSelectedVersion);
document.getElementById("reloadAuditButton").addEventListener("click", refreshAudit);
document.getElementById("auditFilters").addEventListener("change", loadAudit);
els.auditLimit.addEventListener("input", debounce(loadAudit, 250));
els.profileForm.addEventListener("input", debounce(syncProfilePreview, 150));
els.profileForm.addEventListener("change", syncProfilePreview);
els.profileForm.addEventListener("click", handleProfileFormClick);

init();

async function init() {
  await loadHealth();
  await loadProfiles().catch(console.error);
  await refreshAudit();
}

function switchView(viewId) {
  document.querySelectorAll(".nav-tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewId);
  });
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === viewId);
  });
}

async function loadHealth() {
  const health = await apiGet("/api/health");
  const fallback = health.using_fallback ? " fallback" : "";
  const label = health.database_label ? ` - ${health.database_label}` : "";
  els.backendLabel.textContent = `${health.backend}${fallback}${label}`;
}

async function loadProfiles() {
  const payload = await apiGet("/api/profiles");
  state.profiles = payload.profiles || [];
  els.profileCount.textContent = `${state.profiles.length} profile${state.profiles.length === 1 ? "" : "s"}`;
  renderProfileList();
  if (!state.selectedProfileId && state.profiles.length) {
    await selectProfile(state.profiles[0].id);
  }
}

function renderProfileList() {
  els.profileList.innerHTML = "";
  if (!state.profiles.length) {
    const empty = document.createElement("p");
    empty.textContent = "No profiles.";
    els.profileList.appendChild(empty);
    return;
  }

  state.profiles.forEach((profile) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `profile-item${profile.id === state.selectedProfileId ? " is-active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(profile.id)}</strong>
      <span>${escapeHtml(profile.email || "-")}</span>
      <span>${profile.enabled ? "enabled" : "disabled"} - ${escapeHtml(profile.location || "UK")} - ${escapeHtml(profile.language || "default language")} - ${escapeHtml((profile.target_roles || []).join(", ") || "no roles")}</span>
    `;
    button.addEventListener("click", () => selectProfile(profile.id));
    els.profileList.appendChild(button);
  });
}

async function selectProfile(profileId) {
  const payload = await apiGet(`/api/profiles/${encodeURIComponent(profileId)}`);
  state.selectedProfileId = profileId;
  renderProfileForm(payload.profile);
  renderSelectedProfile(payload.summary);
  setProfileStatus("", "");
  renderProfileList();
  await loadProfileVersions(profileId);
}

function newProfile() {
  state.selectedProfileId = "";
  state.versions = [];
  renderProfileForm(defaultProfile());
  renderSelectedProfile({ id: "new-recipient", email: "recipient@example.com", language: "", location: "UK", target_roles: ["swe"], enabled: true });
  renderProfileVersions([]);
  setProfileStatus("", "");
  renderProfileList();
}

async function validateProfile() {
  const profile = readProfileEditor();
  const payload = await apiPost("/api/profiles/validate", { profile });
  renderSelectedProfile(payload.summary);
  setProfileStatus("Valid profile.", "ok");
}

async function normalizeProfile() {
  const profile = readProfileEditor();
  const payload = await apiPost("/api/profiles/validate", { profile });
  renderProfileForm(payload.profile);
  renderSelectedProfile(payload.summary);
  setProfileStatus("Normalized profile.", "ok");
}

async function saveProfile() {
  const profile = readProfileEditor();
  const payload = await apiPost("/api/profiles/save", { profile });
  renderProfileForm(payload.profile);
  state.selectedProfileId = payload.summary.id;
  renderSelectedProfile(payload.summary);
  setProfileStatus("Saved profile.", "ok");
  await loadProfiles();
  await loadProfileVersions(state.selectedProfileId);
  await loadAuditOptions();
}

async function loadProfileVersions(profileId) {
  if (!profileId) {
    renderProfileVersions([]);
    return;
  }
  const payload = await apiGet(`/api/profiles/${encodeURIComponent(profileId)}/versions`);
  state.versions = payload.versions || [];
  renderProfileVersions(state.versions);
}

function renderProfileVersions(versions) {
  els.profileVersionSelect.innerHTML = "";
  els.versionPreview.value = "";
  if (!versions.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No saved versions";
    els.profileVersionSelect.appendChild(option);
    return;
  }

  versions.forEach((version) => {
    const option = document.createElement("option");
    option.value = version.version_id;
    option.textContent = `${version.saved_at || "saved"} - version ${version.version_id}`;
    els.profileVersionSelect.appendChild(option);
  });
}

function selectedVersion() {
  const versionId = els.profileVersionSelect.value;
  return state.versions.find((version) => String(version.version_id) === String(versionId));
}

function compareSelectedVersion() {
  const version = selectedVersion();
  if (!version) {
    setProfileStatus("No profile version selected.", "error");
    return;
  }
  els.versionPreview.value = JSON.stringify(version.profile, null, 2);
  els.versionPanel.open = true;
  setProfileStatus(`Comparing with version ${version.version_id}.`, "ok");
}

async function restoreSelectedVersion() {
  const version = selectedVersion();
  if (!version || !state.selectedProfileId) {
    setProfileStatus("No profile version selected.", "error");
    return;
  }

  const confirmed = window.confirm(`Restore version ${version.version_id} for ${state.selectedProfileId}?`);
  if (!confirmed) {
    return;
  }

  const payload = await apiPost(`/api/profiles/${encodeURIComponent(state.selectedProfileId)}/restore`, {
    version_id: version.version_id,
  });
  renderProfileForm(payload.profile);
  renderSelectedProfile(payload.summary);
  setProfileStatus(`Restored version ${version.version_id}.`, "ok");
  await loadProfiles();
  await loadProfileVersions(payload.summary.id);
}

function handleProfileFormClick(event) {
  const action = event.target.dataset.action;
  if (!action) {
    return;
  }

  const profile = readProfileEditor();
  if (action === "add-role") {
    profile.candidate.target_roles.push({ id: "", name: "", match_text: "" });
  }
  if (action === "remove-role") {
    const index = Number(event.target.dataset.index);
    profile.candidate.target_roles.splice(index, 1);
    if (!profile.candidate.target_roles.length) {
      profile.candidate.target_roles.push({ id: "", name: "", match_text: "" });
    }
  }
  renderProfileForm(profile);
}

function renderProfileForm(profile) {
  const normalized = normalizeProfileForForm(profile || defaultProfile());
  state.currentProfile = normalized;
  els.profileForm.innerHTML = `
    ${profileSection("Profile", "profile", [
      textField("id", "id", normalized.id),
      checkboxField("enabled", "enabled", normalized.enabled),
      textField("delivery.email", "delivery_email", normalized.delivery.email),
      textField("delivery.language", "delivery_language", normalized.delivery.language),
    ].join(""))}
    ${profileSection("Candidate", "candidate", [
      textareaField("candidate.summary", "candidate_summary", normalized.candidate.summary, 5),
      textField("candidate.education_status", "candidate_education_status", normalized.candidate.education_status),
      rolesField(normalized.candidate.target_roles),
    ].join(""))}
    ${profileSection("Job Preferences", "preferences", [
      selectField("job_preferences.location", "preferences_location", normalized.job_preferences.location, ["UK", "Greece"]),
      numberField("job_preferences.target_seniority.max_explicit_years", "seniority_max_explicit_years", normalized.job_preferences.target_seniority.max_explicit_years, "1"),
      numberField("job_preferences.target_seniority.boost_multiplier", "seniority_boost_multiplier", normalized.job_preferences.target_seniority.boost_multiplier, "0.05"),
      textareaField("job_preferences.target_seniority.boost_title_terms", "seniority_boost_title_terms", normalized.job_preferences.target_seniority.boost_title_terms.join("\n"), 4),
      numberField("job_preferences.salary.preferred_max_gbp", "salary_preferred_max_gbp", normalized.job_preferences.salary.preferred_max_gbp, "1000"),
      numberField("job_preferences.salary.hard_cap_gbp", "salary_hard_cap_gbp", normalized.job_preferences.salary.hard_cap_gbp, "1000"),
      numberField("job_preferences.salary.penalty_strength", "salary_penalty_strength", normalized.job_preferences.salary.penalty_strength, "0.05"),
    ].join(""))}
    ${profileSection("Eligibility", "eligibility", [
      checkboxField("eligibility.needs_sponsorship", "eligibility_needs_sponsorship", normalized.eligibility.needs_sponsorship),
      textareaField("eligibility.work_authorization_summary", "eligibility_work_authorization_summary", normalized.eligibility.work_authorization_summary, 3),
      checkboxField("eligibility.check_hard_eligibility", "eligibility_check_hard_eligibility", normalized.eligibility.check_hard_eligibility),
      checkboxField("eligibility.use_sponsor_lookup", "eligibility_use_sponsor_lookup", normalized.eligibility.use_sponsor_lookup),
    ].join(""))}
    ${profileSection("Matching", "matching", [
      numberField("matching.semantic_threshold", "matching_semantic_threshold", normalized.matching.semantic_threshold, "0.01"),
    ].join(""))}
    ${profileSection("LLM Review", "llm", [
      textareaField("llm_review.extra_screening_guidance", "llm_extra_screening_guidance", normalized.llm_review.extra_screening_guidance.join("\n"), 5),
      textareaField("llm_review.extra_final_ranking_guidance", "llm_extra_final_ranking_guidance", normalized.llm_review.extra_final_ranking_guidance.join("\n"), 5),
    ].join(""))}
  `;
  syncProfilePreview();
}

function profileSection(title, sectionKey, content) {
  return `
    <section class="profile-section section-${sectionKey}">
      <div class="section-heading">
        <h4>${escapeHtml(title)}</h4>
        <code>${escapeHtml(sectionKey)}</code>
      </div>
      <div class="field-grid">${content}</div>
    </section>
  `;
}

function textField(path, name, value) {
  return `
    <label class="field-row">
      <span><code>${escapeHtml(path)}</code></span>
      <input data-field="${escapeAttr(name)}" type="text" value="${escapeAttr(value)}">
    </label>
  `;
}

function numberField(path, name, value, step) {
  return `
    <label class="field-row">
      <span><code>${escapeHtml(path)}</code></span>
      <input data-field="${escapeAttr(name)}" type="number" step="${escapeAttr(step)}" value="${escapeAttr(value ?? "")}">
    </label>
  `;
}

function checkboxField(path, name, checked) {
  return `
    <label class="field-row checkbox-row">
      <span><code>${escapeHtml(path)}</code></span>
      <input data-field="${escapeAttr(name)}" type="checkbox" ${checked ? "checked" : ""}>
    </label>
  `;
}

function textareaField(path, name, value, rows) {
  return `
    <label class="field-row field-row-wide">
      <span><code>${escapeHtml(path)}</code></span>
      <textarea data-field="${escapeAttr(name)}" rows="${rows}" spellcheck="false">${escapeHtml(value)}</textarea>
    </label>
  `;
}

function rolesField(roles) {
  const renderedRoles = roles.map((role, index) => `
    <div class="role-item">
      <div class="role-item-header">
        <code>candidate.target_roles[${index}]</code>
        <button type="button" data-action="remove-role" data-index="${index}">Remove</button>
      </div>
      ${textField(`candidate.target_roles[${index}].id`, `role_${index}_id`, role.id)}
      ${textField(`candidate.target_roles[${index}].name`, `role_${index}_name`, role.name)}
      ${textareaField(`candidate.target_roles[${index}].match_text`, `role_${index}_match_text`, role.match_text, 4)}
    </div>
  `).join("");

  return `
    <div class="field-row field-row-wide">
      <div class="array-heading">
        <code>candidate.target_roles</code>
        <button type="button" data-action="add-role">Add Role</button>
      </div>
      <div class="role-list">${renderedRoles}</div>
    </div>
  `;
}

function readProfileEditor() {
  const profile = {
    id: fieldValue("id"),
    enabled: fieldChecked("enabled"),
    delivery: {
      email: fieldValue("delivery_email"),
      language: fieldValue("delivery_language"),
    },
    candidate: {
      summary: fieldValue("candidate_summary"),
      education_status: fieldValue("candidate_education_status"),
      target_roles: readRoles(),
    },
    job_preferences: {
      location: fieldValue("preferences_location"),
      target_seniority: {
        max_explicit_years: optionalNumber("seniority_max_explicit_years"),
        boost_multiplier: optionalNumber("seniority_boost_multiplier"),
        boost_title_terms: textLines("seniority_boost_title_terms"),
      },
      salary: {
        preferred_max_gbp: optionalNumber("salary_preferred_max_gbp"),
        hard_cap_gbp: optionalNumber("salary_hard_cap_gbp"),
        penalty_strength: optionalNumber("salary_penalty_strength"),
      },
    },
    eligibility: {
      needs_sponsorship: fieldChecked("eligibility_needs_sponsorship"),
      work_authorization_summary: fieldValue("eligibility_work_authorization_summary"),
      check_hard_eligibility: fieldChecked("eligibility_check_hard_eligibility"),
      use_sponsor_lookup: fieldChecked("eligibility_use_sponsor_lookup"),
    },
    matching: {
      semantic_threshold: optionalNumber("matching_semantic_threshold"),
    },
    llm_review: {
      extra_screening_guidance: textLines("llm_extra_screening_guidance"),
      extra_final_ranking_guidance: textLines("llm_extra_final_ranking_guidance"),
    },
  };
  state.currentProfile = profile;
  return profile;
}

function readRoles() {
  const roles = [];
  els.profileForm.querySelectorAll(".role-item").forEach((roleElement, index) => {
    roles.push({
      id: fieldValue(`role_${index}_id`),
      name: fieldValue(`role_${index}_name`),
      match_text: fieldValue(`role_${index}_match_text`),
    });
  });
  return roles;
}

function syncProfilePreview() {
  try {
    const profile = readProfileEditor();
    els.profileEditor.value = JSON.stringify(profile, null, 2);
    renderSelectedProfile({
      id: profile.id,
      email: profile.delivery.email,
      language: profile.delivery.language,
      location: profile.job_preferences.location,
      enabled: profile.enabled,
      target_roles: profile.candidate.target_roles.map((role) => role.id).filter(Boolean),
    });
  } catch (error) {
    setProfileStatus(error.message, "error");
  }
}

function renderSelectedProfile(summary) {
  const roles = (summary?.target_roles || []).join(", ") || "no roles";
  const language = summary?.language || "default language";
  const location = summary?.location || "UK";
  els.selectedProfileTitle.textContent = summary?.id || "No profile selected";
  els.selectedProfileMeta.textContent = `${summary?.email || "-"} - ${summary?.enabled ? "enabled" : "disabled"} - ${location} - ${language} - ${roles}`;
}

function selectField(path, name, value, options) {
  const renderedOptions = options.map((option) => `
    <option value="${escapeAttr(option)}" ${option === value ? "selected" : ""}>${escapeHtml(option)}</option>
  `).join("");
  return `
    <label class="field-row">
      <span><code>${escapeHtml(path)}</code></span>
      <select data-field="${escapeAttr(name)}">${renderedOptions}</select>
    </label>
  `;
}

function setProfileStatus(message, kind) {
  els.profileStatus.textContent = message;
  els.profileStatus.className = `status-line ${kind || ""}`.trim();
}

function normalizeProfileForForm(profile) {
  const candidate = profile.candidate || {};
  const preferences = profile.job_preferences || {};
  const seniority = preferences.target_seniority || {};
  const salary = preferences.salary || {};
  const eligibility = profile.eligibility || {};
  const matching = profile.matching || {};
  const llm = profile.llm_review || {};
  const roles = Array.isArray(candidate.target_roles) && candidate.target_roles.length
    ? candidate.target_roles
    : [{ id: "swe", name: "", match_text: "" }];

  return {
    id: profile.id || "",
    enabled: profile.enabled !== false,
    delivery: {
      email: (profile.delivery || {}).email || profile.email || "",
      language: (profile.delivery || {}).language || "",
    },
    candidate: {
      summary: candidate.summary || "",
      education_status: candidate.education_status || "",
      target_roles: roles.map((role) => ({
        id: role.id || role.profile_id || role.name || "",
        name: role.name || "",
        match_text: role.match_text || role.text || role.profile_text || "",
      })),
    },
    job_preferences: {
      location: preferences.location || "UK",
      target_seniority: {
        max_explicit_years: seniority.max_explicit_years ?? "",
        boost_multiplier: seniority.boost_multiplier ?? "",
        boost_title_terms: normalizeArray(seniority.boost_title_terms),
      },
      salary: {
        preferred_max_gbp: salary.preferred_max_gbp ?? "",
        hard_cap_gbp: salary.hard_cap_gbp ?? "",
        penalty_strength: salary.penalty_strength ?? "",
      },
    },
    eligibility: {
      needs_sponsorship: Boolean(eligibility.needs_sponsorship),
      work_authorization_summary: eligibility.work_authorization_summary || "",
      check_hard_eligibility: Boolean(eligibility.check_hard_eligibility),
      use_sponsor_lookup: Boolean(eligibility.use_sponsor_lookup),
    },
    matching: {
      semantic_threshold: matching.semantic_threshold ?? "",
    },
    llm_review: {
      extra_screening_guidance: normalizeArray(llm.extra_screening_guidance),
      extra_final_ranking_guidance: normalizeArray(llm.extra_final_ranking_guidance),
    },
  };
}

function defaultProfile() {
  return {
    id: "new-recipient",
    enabled: true,
    delivery: {
      email: "recipient@example.com",
      language: "",
    },
    candidate: {
      summary: "",
      education_status: "",
      target_roles: [
        {
          id: "swe",
          name: "",
          match_text: "",
        },
      ],
    },
    job_preferences: {
      location: "UK",
      target_seniority: {
        max_explicit_years: 1,
        boost_multiplier: 1.2,
        boost_title_terms: ["junior", "grad", "graduate", "entry level", "entry-level"],
      },
      salary: {
        preferred_max_gbp: null,
        hard_cap_gbp: null,
        penalty_strength: 0.35,
      },
    },
    eligibility: {
      needs_sponsorship: false,
      work_authorization_summary: "",
      check_hard_eligibility: false,
      use_sponsor_lookup: false,
    },
    matching: {
      semantic_threshold: 0.42,
    },
    llm_review: {
      extra_screening_guidance: [],
      extra_final_ranking_guidance: [],
    },
  };
}

function fieldElement(name) {
  return els.profileForm.querySelector(`[data-field="${name}"]`);
}

function fieldValue(name) {
  return (fieldElement(name)?.value || "").trim();
}

function fieldChecked(name) {
  return Boolean(fieldElement(name)?.checked);
}

function optionalNumber(name) {
  const value = fieldValue(name);
  if (value === "") {
    return null;
  }
  return Number(value);
}

function textLines(name) {
  return fieldValue(name)
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function normalizeArray(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

async function loadAuditOptions() {
  const options = await apiGet("/api/audit/options");
  fillSelect(els.auditRecipient, options.recipient_ids || [], "All");
  fillSelect(els.auditFamily, options.review_families || [], "All");
  fillSelect(els.auditClassification, options.classifications || [], "All");
  fillSelect(els.auditRun, options.run_ids || [], "All");
}

async function refreshAudit() {
  await loadAuditOptions();
  await loadAudit();
}

async function loadAudit() {
  const params = new URLSearchParams();
  for (const [name, element] of [
    ["recipient_id", els.auditRecipient],
    ["review_family", els.auditFamily],
    ["classification", els.auditClassification],
    ["run_id", els.auditRun],
    ["limit", els.auditLimit],
    ["sort", els.auditSort],
  ]) {
    if (element.value) {
      params.set(name, element.value);
    }
  }

  const payload = await apiGet(`/api/audit?${params.toString()}`);
  const rows = payload.rows || [];
  els.auditCount.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  renderAuditSummary(payload.summary || {});
  renderAuditRows(rows);
}

function renderAuditSummary(summary) {
  els.auditSummary.innerHTML = "";
  const classifications = summary.classifications || {};
  Object.entries(classifications).slice(0, 8).forEach(([name, count]) => {
    els.auditSummary.appendChild(pill(`${name}: ${count}`));
  });
}

function renderAuditRows(rows) {
  els.auditRows.innerHTML = "";
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No audit rows.";
    els.auditRows.appendChild(empty);
    return;
  }

  rows.forEach((row) => {
    const item = document.createElement("article");
    item.className = "audit-row";
    const classificationKind = row.classification?.includes("failed")
      ? " failure"
      : row.classification?.includes("rejected") || row.classification?.includes("below")
        ? " warning"
        : "";
    item.innerHTML = `
      <div>
        <span class="classification${classificationKind}">${escapeHtml(row.classification || "-")}</span>
        <h3>${escapeHtml(row.recipient_id || "-")}</h3>
        <p>${escapeHtml(row.review_family || "-")} - ${escapeHtml(row.stage || "-")}</p>
        <p>${escapeHtml(row.created_at || "")}</p>
      </div>
      <div>
        <h3>${escapeHtml(row.company_name || "-")}</h3>
        <p>${escapeHtml(row.title || "-")}</p>
        <p>${escapeHtml(row.location || "-")}</p>
        ${row.job_url ? `<a href="${escapeAttr(row.job_url)}" target="_blank" rel="noreferrer">${escapeHtml(row.job_url)}</a>` : ""}
      </div>
      <div class="audit-meta">
        ${scoreLine(row)}
        ${semanticLine(row)}
        ${row.hard_filter_reason ? `<div>Hard filter: ${escapeHtml(row.hard_filter_reason)}</div>` : ""}
        ${row.gemini_reason ? `<div>Gemini: ${escapeHtml(row.gemini_reason)}</div>` : ""}
        ${row.review_error_stage ? `<div>Error stage: ${escapeHtml(row.review_error_stage)}</div>` : ""}
        ${row.review_error ? `<div>Error: ${escapeHtml(row.review_error)}</div>` : ""}
        ${evidenceBlock("Evidence", row.supporting_evidence)}
        ${evidenceBlock("Mismatch", row.mismatch_evidence)}
      </div>
    `;
    els.auditRows.appendChild(item);
  });
}

function scoreLine(row) {
  const parts = [];
  if (row.raw_embedding_score !== null && row.raw_embedding_score !== undefined) {
    parts.push(`raw ${Number(row.raw_embedding_score).toFixed(3)}`);
  }
  if (row.semantic_score !== null && row.semantic_score !== undefined) {
    parts.push(`final ${Number(row.semantic_score).toFixed(3)}`);
  }
  if (row.semantic_threshold !== null && row.semantic_threshold !== undefined) {
    parts.push(`threshold ${Number(row.semantic_threshold).toFixed(3)}`);
  }
  if (row.gemini_pass1_score !== null && row.gemini_pass1_score !== undefined) {
    parts.push(`pass1 ${row.gemini_pass1_score}`);
  }
  if (row.gemini_pass2_score !== null && row.gemini_pass2_score !== undefined) {
    parts.push(`pass2 ${row.gemini_pass2_score}`);
  }
  return parts.length ? `<div>${escapeHtml(parts.join(" - "))}</div>` : "";
}

function semanticLine(row) {
  const lines = [];
  if (row.semantic_rank !== null && row.semantic_rank !== undefined) {
    lines.push(`rank ${row.semantic_rank}`);
  }
  if (row.semantic_top_profile) {
    lines.push(`top ${row.semantic_top_profile}`);
  }
  if (row.semantic_second_profile) {
    lines.push(`second ${row.semantic_second_profile}`);
  }

  const fitSummary = row.semantic_fit_summary
    ? `<div class="audit-evidence">Fit: ${escapeHtml(row.semantic_fit_summary)}</div>`
    : "";
  const compact = lines.length ? `<div>${escapeHtml(lines.join(" - "))}</div>` : "";
  return compact + fitSummary;
}

function evidenceBlock(label, values) {
  if (!Array.isArray(values) || !values.length) {
    return "";
  }
  const text = values.map((value) => String(value)).join(" | ");
  return `<div class="audit-evidence">${label}: ${escapeHtml(text)}</div>`;
}

function fillSelect(select, values, allLabel) {
  const currentValue = select.value;
  select.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = allLabel;
  select.appendChild(allOption);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  select.value = values.includes(currentValue) ? currentValue : "";
}

function pill(text) {
  const element = document.createElement("span");
  element.className = "pill";
  element.textContent = text;
  return element;
}

async function apiGet(path) {
  return api(path, { method: "GET" });
}

async function apiPost(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) {
    const message = payload.error || `Request failed: ${response.status}`;
    if (path.includes("/profiles/")) {
      setProfileStatus(message, "error");
    }
    throw new Error(message);
  }
  return payload;
}

function debounce(callback, delay) {
  let timer = null;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(callback, delay);
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
