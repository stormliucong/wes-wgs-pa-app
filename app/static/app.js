// Simple multi-step form logic with client-side validation and JSON submission
(function () {
  const steps = Array.from(document.querySelectorAll('.form-step'));
  const nextBtns = Array.from(document.querySelectorAll('[data-next]'));
  const prevBtns = Array.from(document.querySelectorAll('[data-prev]'));
  const submitBtn = document.querySelector('#submitBtn');
  const form = document.querySelector('#pa-form');
  const alertBox = document.querySelector('#alert-box');
  const errorsBox = document.querySelector('#form-errors');
  const resetFormBtn = document.querySelector('#resetFormBtn');

  // Subscriber / primary insurance controls
  const subscriberDetails = document.querySelector('#subscriber-details');
  const primarySubscriberYes = document.querySelector('#primary_subscriber_yes');
  const primarySubscriberNo = document.querySelector('#primary_subscriber_no');
  const subscriberNameInput = document.querySelector('#subscriber_name');
  const subscriberDobInput = document.querySelector('#subscriber_dob');
  const subscriberRelationSelect = document.querySelector('#subscriber_relation');
  const subscriberRelationOtherInput = document.querySelector('#subscriber_relation_other');
  const subscriberRelationOtherWrapper = document.querySelector('#subscriber_relation_other_wrapper');

  // Lab code modal controls
  const searchLabCodeBtn = document.querySelector('#search-test-code-btn');
  const labCodesModal = document.querySelector('#lab-codes-modal');
  const closeModalBtn = document.querySelector('#close-modal-btn');

  // Dynamic lists containers
  const icdList = document.querySelector('#icd-list');
  const addIcdBtn = document.querySelector('#add-icd');
  const priorTestsList = document.querySelector('#prior-tests-list');
  const addPriorTestBtn = document.querySelector('#add-prior-test');
  const priorTestNegativeCheckbox = document.querySelector('#prior_test_negative');
  const rationalePriorTest = document.querySelector('#rationale-prior-test');
  const rationalePriorTestType = document.querySelector('#rationale_prior_test_type');
  const rationalePriorTestResult = document.querySelector('#rationale_prior_test_result');
  const rationalePriorTestDate = document.querySelector('#rationale_prior_test_date');

  function updateSubscriberDetailsVisibility() {
    if (!subscriberDetails) return;
    const show = primarySubscriberNo && primarySubscriberNo.checked;

    subscriberDetails.style.display = show ? '' : 'none';

    const fields = [subscriberNameInput, subscriberDobInput, subscriberRelationSelect];
    fields.forEach((el) => {
      if (!el) return;
      if (show) {
        el.required = true;
      } else {
        el.required = false;
        if (el.tagName === 'SELECT') {
          el.selectedIndex = 0;
        } else {
          el.value = '';
        }
      }
    });

    // When hiding all subscriber details, also hide and clear the Other relationship details
    if (!show && subscriberRelationOtherWrapper) {
      subscriberRelationOtherWrapper.style.display = 'none';
    }
    if (!show && subscriberRelationOtherInput) {
      subscriberRelationOtherInput.required = false;
      subscriberRelationOtherInput.value = '';
    }

    updateSubscriberRelationOtherVisibility();
  }

  function updateSubscriberRelationOtherVisibility() {
    if (!subscriberRelationSelect || !subscriberRelationOtherWrapper) return;
    const showOther = subscriberDetails && subscriberDetails.style.display !== 'none' && subscriberRelationSelect.value === 'Other';
    subscriberRelationOtherWrapper.style.display = showOther ? '' : 'none';
    if (subscriberRelationOtherInput) {
      subscriberRelationOtherInput.required = showOther;
      if (!showOther) subscriberRelationOtherInput.value = '';
    }
  }

  function updateRationalePriorTestVisibility() {
    if (!rationalePriorTest || !priorTestNegativeCheckbox) return;
    const show = priorTestNegativeCheckbox.checked;
    rationalePriorTest.style.display = show ? '' : 'none';
    if (rationalePriorTestType) rationalePriorTestType.required = show;
    if (rationalePriorTestResult) rationalePriorTestResult.required = show;
    if (rationalePriorTestDate) rationalePriorTestDate.required = show;
    if (!show) {
      if (rationalePriorTestType) rationalePriorTestType.selectedIndex = 0;
      if (rationalePriorTestResult) rationalePriorTestResult.value = '';
      if (rationalePriorTestDate) rationalePriorTestDate.value = '';
    }
  }

  // ICD code row generator
  function createIcdRow() {
    const row = document.createElement('div');
    row.className = 'icd-row';
    row.innerHTML = `
      <div class="grid" style="margin-bottom:0.5rem;">
        <div class="col-5">
          <input name="icd_code[]" placeholder="ICD Code" required />
        </div>
        <div class="col-5">
          <input name="icd_description[]" placeholder="Description" />
        </div>
        <div class="col-2" style="display:flex; align-items:end; justify-content:center;">
          <button type="button" class="secondary remove-icd" style="padding:0.25rem 0.5rem;">×</button>
        </div>
      </div>
    `;
    return row;
  }

  // Update form data collection for ICD codes
  function collectIcdCodesData() {
    const rows = document.querySelectorAll('.icd-row');
    return Array.from(rows)
      .map((row) => row.querySelector('input[name="icd_code[]"]').value)
      .map((code) => code.trim())
      .filter((code) => code.length > 0);
  }

  function createPriorTestRow() {
    const row = document.createElement('div');
    row.className = 'grid';
    row.innerHTML = `
      <div class="col-4">
        <select name="prior_test_type">
          <option value="CMA">CMA</option>
          <option value="Gene Panel">Gene Panel</option>
          <option value="Single Gene">Single Gene</option>
          <option value="mtDNA">mtDNA</option>
          <option value="Karyotype">Karyotype</option>
          <option value="Fragile X">Fragile X</option>
          <option value="Other">Other</option>
        </select>
      </div>
      <div class="col-4">
        <input name="prior_test_result" placeholder="Result" />
      </div>
      <div class="col-3">
        <input name="prior_test_date" type="date" />
      </div>
      <div class="col-1">
        <button type="button" class="secondary remove-prior-test">✕</button>
      </div>`;
    row.querySelector('.remove-prior-test').addEventListener('click', () => row.remove());
    return row;
  }

  // Initialize with ICD search
  if (icdList && icdList.children.length === 0) {
    // No need to initialize - search-based system
  }
  if (priorTestsList && priorTestsList.children.length === 0) {
    priorTestsList.appendChild(createPriorTestRow());
  }
  if (addPriorTestBtn) {
    addPriorTestBtn.addEventListener('click', () => priorTestsList.appendChild(createPriorTestRow()));
  }

  // ICD code dynamic list
  if (icdList && addIcdBtn) {
    // Don't create initial row here - let the draft load handle it
    addIcdBtn.addEventListener('click', () => icdList.appendChild(createIcdRow()));
    icdList.addEventListener('click', (e) => {
      if (e.target.classList.contains('remove-icd')) {
        const row = e.target.closest('.icd-row');
        if (row) row.remove();
      }
    });
  }

  // Wire up primary-subscriber question
  if (primarySubscriberYes) {
    primarySubscriberYes.addEventListener('change', updateSubscriberDetailsVisibility);
  }
  if (primarySubscriberNo) {
    primarySubscriberNo.addEventListener('change', updateSubscriberDetailsVisibility);
  }
  if (subscriberRelationSelect) {
    subscriberRelationSelect.addEventListener('change', updateSubscriberRelationOtherVisibility);
  }
  if (priorTestNegativeCheckbox) {
    priorTestNegativeCheckbox.addEventListener('change', updateRationalePriorTestVisibility);
  }
  // Initialize visibility on load
  updateSubscriberDetailsVisibility();
  updateRationalePriorTestVisibility();

  // Wire up lab code modal
  if (searchLabCodeBtn && labCodesModal) {
    searchLabCodeBtn.addEventListener('click', () => {
      labCodesModal.style.display = 'block';
    });
  }
  if (closeModalBtn && labCodesModal) {
    closeModalBtn.addEventListener('click', () => {
      labCodesModal.style.display = 'none';
    });
  }

  let current = 0;
  function showStep(i) {
    console.log(`Switching to step index: ${i}`);
    steps.forEach((s, idx) => {
      const isActive = idx === i;
      s.classList.toggle('active', isActive);
      console.log(`Step ${idx} is ${isActive ? 'active' : 'inactive'}`);
    });
    current = i;
    try { localStorage.setItem('pa_current_step', String(i)); } catch (_) {}
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  showStep(0);

  function getHumanReadableLabel(fieldName, element) {
    // Map of field names to human-readable labels
    const labelMap = {
      'patient_first_name': 'First Name',
      'patient_last_name': 'Last Name',
      'patient_dob': 'Date of Birth',
      'member_id': 'Member/Policy ID',
      'provider_name': 'Provider Name',
      'provider_npi': 'Provider NPI',
      'test_type': 'Test Type',
      'icd_codes': 'ICD Codes',
      'cpt_codes': 'CPT Codes',
      'consent_ack': 'Consent'
    };
    
    // Try to get from our map first
    if (labelMap[fieldName]) {
      return labelMap[fieldName];
    }
    
    // Try to get from associated label element
    if (element && element.labels && element.labels[0]) {
      return element.labels[0].textContent.trim();
    }
    
    // Fallback: convert field name to title case
    return fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  function validateStep(i) {
    const stepEl = steps[i];
    const required = stepEl.querySelectorAll('[required]');
    const allInputs = stepEl.querySelectorAll('input, select, textarea');
    let ok = true;
    let errorMessages = [];

    const seenRadioNames = new Set();

    // Check required fields
    required.forEach((el) => {
      if (el.type === 'radio') {
        if (seenRadioNames.has(el.name)) return;
        seenRadioNames.add(el.name);
        const group = stepEl.querySelectorAll(`input[type="radio"][name="${el.name}"]`);
        const anyChecked = Array.from(group).some((r) => r.checked);
        if (!anyChecked) {
          ok = false;
          const fieldLabel = getHumanReadableLabel(el.name, el);
          errorMessages.push(`${fieldLabel} is required`);
        }
        return;
      }
      if (el.type === 'checkbox') {
        if (!el.checked) {
          ok = false;
          const fieldLabel = getHumanReadableLabel(el.name, el);
          errorMessages.push(`${fieldLabel} is required`);
        }
      } else if (!el.value || el.value.trim() === '') {
        ok = false;
        const fieldLabel = getHumanReadableLabel(el.name, el);
        errorMessages.push(`${fieldLabel} is required`);
      }
    });

    // Special validation for ICD codes - at least one row must exist
    if (stepEl.querySelector('#icd-list')) {
      const icdRows = stepEl.querySelectorAll('.icd-row');
      if (icdRows.length === 0) {
        ok = false;
        errorMessages.push('At least one ICD code is required');
      }
    }

    // Special validation for rationale checkboxes - at least one must be selected
    if (stepEl.querySelector('.checkbox-group')) {
      const rationaleCheckboxes = stepEl.querySelectorAll('.checkbox-group input[type="checkbox"]');
      const hasSelectedRationale = Array.from(rationaleCheckboxes).some(checkbox => checkbox.checked);
      if (!hasSelectedRationale) {
        ok = false;
        errorMessages.push('At least one rationale checkbox must be selected');
      }
    }

    // Additional format validation for all fields (not just required ones)
    allInputs.forEach((el) => {
      const value = el.value?.trim();
      if (value) { // Only validate if field has a value
        if (el.name === 'provider_npi' || el.name === 'lab_npi') {
          if (!/^\d{10}$/.test(value)) {
            ok = false;
            const fieldLabel = getHumanReadableLabel(el.name, el);
            errorMessages.push(`${fieldLabel} must be exactly 10 digits`);
          }
        }
      }
    });

    // Display error messages
    if (errorsBox) {
      if (errorMessages.length > 0) {
        errorsBox.innerHTML = errorMessages.map(msg => `<p>${msg}</p>`).join('');
        errorsBox.style.display = 'block';
      } else {
        errorsBox.style.display = 'none';
      }
    }

    return ok;
  }

  nextBtns.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const stepIndex = steps.indexOf(btn.closest('.form-step'));
      if (!validateStep(stepIndex)) {
        e.preventDefault();
        // Ensure error messages are displayed immediately
        errorsBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      showStep(stepIndex + 1);
    });
  });

  prevBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.prev, 10);
      clearError();
      showStep(idx);
    });
  });

  function showError(msg) {
    errorsBox.textContent = msg;
    errorsBox.style.display = 'block';
  }
  function clearError() {
    errorsBox.textContent = '';
    errorsBox.style.display = 'none';
  }
  function showAlert(type, msg) {
    alertBox.className = 'alert ' + (type === 'error' ? 'error' : '');
    alertBox.textContent = msg;
    alertBox.style.display = 'block';
  }

  // Persistent form identifiers and timestamps
  function getFormId() {
    let id = localStorage.getItem('pa_form_id');
    if (!id && window.crypto && crypto.randomUUID) {
      id = crypto.randomUUID();
      localStorage.setItem('pa_form_id', id);
    }
    return id || '';
  }

  function getStartedAt() {
    let s = localStorage.getItem('pa_started_at');
    if (!s) {
      s = new Date().toISOString();
      localStorage.setItem('pa_started_at', s);
    }
    return s;
  }

  function setNewFormMeta(formId, startedAt) {
    localStorage.setItem('pa_form_id', formId);
    localStorage.setItem('pa_started_at', startedAt);
    localStorage.setItem('pa_current_step', '0');
  }

  function collectFormData() {
    const data = {};
    const fields = form.querySelectorAll('input, select, textarea');
    const arrFields = new Map();
    fields.forEach((f) => {
      const name = f.name;
      if (!name) return;
      if (name === 'icd_code[]' || name === 'icd_description[]') {
        return;
      }
      if (f.type === 'checkbox' && f.name === 'cpt_codes') {
        // collect multiple checked CPTs
        arrFields.set('cpt_codes', (arrFields.get('cpt_codes') || []));
        if (f.checked) arrFields.get('cpt_codes').push(f.value);
        return;
      }
      if (name === 'prior_test_type' || name === 'prior_test_result' || name === 'prior_test_date') {
        arrFields.set(name, (arrFields.get(name) || []));
        arrFields.get(name).push(f.value);
        return;
      }
      if (f.type === 'checkbox') {
        data[name] = f.checked;
      } else if (f.type === 'radio') {
        if (f.checked) data[name] = f.value;
      } else {
        data[name] = f.value;
      }
    });
    
    // Collect ICD codes from the new search-based system
    data.icd_codes = collectIcdCodesData();

    
    // Merge other array fields
    for (const [k, v] of arrFields.entries()) {
      data[k] = v;
    }
    // Include meta
    data.form_id = getFormId();
    data.started_at = getStartedAt();
    return data;
  }

  function populateForm(data) {
    if (!data || typeof data !== 'object') return;

    // Simple inputs and selects
    const fields = form.querySelectorAll('input[name], select[name], textarea[name]');
    fields.forEach((f) => {
      const name = f.name;
      if (!name) return;
      if (name === 'icd_codes' || name === 'icd_desc' || name === 'prior_test_type' || name === 'prior_test_result' || name === 'prior_test_date' || name === 'cpt_codes') {
        return; // handled separately
      }
      let val = data[name];
      if (typeof val === 'undefined') return;
      if (f.type === 'checkbox') {
        f.checked = !!val;
      } else if (f.type === 'radio') {
        f.checked = f.value === String(val);
      } else {
        f.value = val;
      }
    });

    // CPT codes (array)
    const cptVals = Array.isArray(data.cpt_codes) ? data.cpt_codes : [];
    cptVals.forEach((code) => {
      const el = form.querySelector(`input[type="checkbox"][name="cpt_codes"][value="${code}"]`);
      if (el) el.checked = true;
    });

    // ICD codes - restore from saved data
    const icds = Array.isArray(data.icd_codes) ? data.icd_codes : [];
    if (icdList) {
      icdList.innerHTML = '';
      // Filter out any corrupted/stringified data
      const validIcds = icds.filter((icd) => {
        if (typeof icd === 'string') return icd.trim().length > 0 && !icd.startsWith('{');
        if (icd && typeof icd === 'object') return true;
        return false;
      });
      
      if (validIcds.length === 0) {
        // If no valid data, create one empty row
        icdList.appendChild(createIcdRow());
      } else {
        validIcds.forEach((icd) => {
          const row = createIcdRow();
          const codeInput = row.querySelector('input[name="icd_code[]"]');
          const descInput = row.querySelector('input[name="icd_description[]"]');
          if (typeof icd === 'string') {
            codeInput.value = icd;
          } else if (icd && typeof icd === 'object') {
            codeInput.value = icd.code || '';
            descInput.value = icd.description || '';
          }
          icdList.appendChild(row);
        });
      }
    }

    // Prior tests rows
    const ptTypes = Array.isArray(data.prior_test_type) ? data.prior_test_type : [];
    const ptResults = Array.isArray(data.prior_test_result) ? data.prior_test_result : [];
    const ptDates = Array.isArray(data.prior_test_date) ? data.prior_test_date : [];
    const maxLen = Math.max(ptTypes.length, ptResults.length, ptDates.length);
    if (priorTestsList) {
      priorTestsList.innerHTML = '';
      if (maxLen === 0) {
        priorTestsList.appendChild(createPriorTestRow());
      } else {
        for (let i = 0; i < maxLen; i++) {
          const row = createPriorTestRow();
          const typeSel = row.querySelector('select[name="prior_test_type"]');
          const resInp = row.querySelector('input[name="prior_test_result"]');
          const dateInp = row.querySelector('input[name="prior_test_date"]');
          if (typeSel) typeSel.value = ptTypes[i] || typeSel.value;
          if (resInp) resInp.value = ptResults[i] || '';
          if (dateInp) dateInp.value = ptDates[i] || '';
          priorTestsList.appendChild(row);
        }
      }
    }

    // Ensure subscriber details visibility matches loaded data
    updateSubscriberDetailsVisibility();
    updateSubscriberRelationOtherVisibility();
    updateRationalePriorTestVisibility();
  }

  async function saveDraft(silent = true) {
    const payload = collectFormData();
    payload.current_step = current;
    try {
      const res = await fetch('/draft/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok || !body.ok) {
        if (!silent) showAlert('error', body?.error || 'Failed to save draft');
      } else {
        if (body.form_id) localStorage.setItem('pa_form_id', body.form_id);
        if (body.started_at) localStorage.setItem('pa_started_at', body.started_at);
        if (!silent) showAlert('success', 'Draft saved');
      }
    } catch (err) {
      if (!silent) showAlert('error', 'Network or server error while saving draft');
    }
  }

  // Load draft on page ready
  window.addEventListener('DOMContentLoaded', async () => {
    try {
      // Ensure a form exists server-side
      let formId = getFormId();
      let startedAt = getStartedAt();
      if (!formId || !startedAt) {
        const resNew = await fetch('/draft/start_new', { method: 'POST' });
        const bodyNew = await resNew.json();
        if (resNew.ok && bodyNew.ok) {
          setNewFormMeta(bodyNew.form_id, bodyNew.started_at);
          formId = bodyNew.form_id;
          startedAt = bodyNew.started_at;
        }
      }

      const res = await fetch('/draft/load?form_id=' + encodeURIComponent(formId));
      const body = await res.json();
      if (res.ok && body.ok && body.payload) {
        populateForm(body.payload);
        const stepFromServer = parseInt(body.current_step, 10);
        if (!Number.isNaN(stepFromServer) && stepFromServer >= 0 && stepFromServer < steps.length) {
          showStep(stepFromServer);
        } else {
          // Fallback to localStorage if server didn't include current_step
          const lsStep = parseInt((localStorage.getItem('pa_current_step') || ''), 10);
          if (!Number.isNaN(lsStep) && lsStep >= 0 && lsStep < steps.length) showStep(lsStep);
        }
      } else {
        const lsStep = parseInt((localStorage.getItem('pa_current_step') || ''), 10);
        if (!Number.isNaN(lsStep) && lsStep >= 0 && lsStep < steps.length) showStep(lsStep);
      }
    } catch (_) {
      // On error, still try localStorage
      const lsStep = parseInt((localStorage.getItem('pa_current_step') || ''), 10);
      if (!Number.isNaN(lsStep) && lsStep >= 0 && lsStep < steps.length) showStep(lsStep);
    }
    // Autosave periodically
    setInterval(() => { saveDraft(true); }, 20000);
  });

  // Delete current form and start a new one
  if (resetFormBtn) {
    resetFormBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      const formId = localStorage.getItem('pa_form_id');
      if (!formId) { form.reset(); showStep(0); return; }
      if (!confirm('Delete the current form in progress?')) return;
      try {
        const res = await fetch('/draft/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ form_id: formId })
        });
        const body = await res.json();
        if (res.ok && body.ok) {
          const resNew = await fetch('/draft/start_new', { method: 'POST' });
          const bodyNew = await resNew.json();
          if (resNew.ok && bodyNew.ok) {
            setNewFormMeta(bodyNew.form_id, bodyNew.started_at);
          } else {
            setNewFormMeta((crypto.randomUUID && crypto.randomUUID()) || String(Date.now()), new Date().toISOString());
          }
          form.reset();
          if (icdList) { icdList.innerHTML = ''; icdList.appendChild(createIcdRow()); }
          if (priorTestsList) { priorTestsList.innerHTML = ''; priorTestsList.appendChild(createPriorTestRow()); }
          showStep(0);
          showAlert('success', 'Deleted current form and started a new one.');
        } else {
          showAlert('error', body?.error || 'Failed to delete current form');
        }
      } catch (_) {
        showAlert('error', 'Network error while deleting form');
      }
    });
  }

  // Auto-save on page unload using Beacon
  window.addEventListener('beforeunload', () => {
    try {
      const payload = collectFormData();
      payload.current_step = current;
      const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
      navigator.sendBeacon('/draft/save', blob);
    } catch (_) {
      // ignore errors
    }
  });

  if (submitBtn) {
    submitBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (!validateStep(current)) {
        // validateStep() already calls showError() with specific messages
        return;
      }
      const primaryVal = (primarySubscriberYes && primarySubscriberYes.checked)
        ? 'yes'
        : (primarySubscriberNo && primarySubscriberNo.checked) ? 'no' : '';
      if (primaryVal === 'no') {
        const missingSubscriber =
          !subscriberNameInput?.value?.trim() ||
          !subscriberDobInput?.value?.trim() ||
          !subscriberRelationSelect?.value?.trim() ||
          (subscriberRelationSelect?.value === 'Other' && !subscriberRelationOtherInput?.value?.trim());
        if (missingSubscriber) {
          showError('Subscriber details are required when the patient is not the primary subscriber.');
          showStep(0);
          errorsBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
          return;
        }
      }
      clearError();

      const payload = collectFormData();
      try {
        submitBtn.disabled = true;
        const res = await fetch('/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        let body = {};
        try {
          body = await res.json();
        } catch (_) {
          body = {};
        }
        if (!res.ok) {
          if (body && body.errors) {
            const msgs = Object.entries(body.errors)
              .map(([k, v]) => `${k}: ${v}`)
              .join('\n');
            showAlert('error', 'Fix the following errors before submitting:\n' + msgs);
          } else {
            const statusMsg = `Submission failed (HTTP ${res.status}).`;
            showAlert('error', body?.message || statusMsg);
          }
          return;
        }
        showAlert('success', 'Submitted successfully. Reference: ' + (body.file || 'n/a'));
        // After submission, start a new form automatically
        try {
          const resNew = await fetch('/draft/start_new', { method: 'POST' });
          const bodyNew = await resNew.json();
          if (resNew.ok && bodyNew.ok) {
            setNewFormMeta(bodyNew.form_id, bodyNew.started_at);
          }
        } catch (_) {}
        form.reset();
        // reset dynamic lists to one row each
        if (icdList) {
          icdList.innerHTML = '';
          icdList.appendChild(createIcdRow());
        }
        if (priorTestsList) {
          priorTestsList.innerHTML = '';
          priorTestsList.appendChild(createPriorTestRow());
        }
        showStep(0);
      } catch (err) {
        showAlert('error', 'Network or server error. Please try again.');
      } finally {
        submitBtn.disabled = false;
      }
    });
  }
})();
