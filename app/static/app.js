// Simple multi-step form logic with client-side validation and JSON submission
(function () {
  const steps = Array.from(document.querySelectorAll('.form-step'));
  const nextBtns = Array.from(document.querySelectorAll('[data-next]'));
  const prevBtns = Array.from(document.querySelectorAll('[data-prev]'));
  const submitBtn = document.querySelector('#submitBtn');
  const form = document.querySelector('#pa-form');
  const alertBox = document.querySelector('#alert-box');
  const errorsBox = document.querySelector('#form-errors');
  const saveDraftBtn = document.querySelector('#saveDraftBtn');

  // Lab code modal controls
  const searchLabCodeBtn = document.querySelector('#search-test-code-btn');
  const labCodesModal = document.querySelector('#lab-codes-modal');
  const closeModalBtn = document.querySelector('#close-modal-btn');

  // Dynamic lists containers
  const icdList = document.querySelector('#icd-list');
  const addIcdBtn = document.querySelector('#add-icd');
  const priorTestsList = document.querySelector('#prior-tests-list');
  const addPriorTestBtn = document.querySelector('#add-prior-test');

  function createIcdRow(value = '') {
    const row = document.createElement('div');
    row.className = 'grid';
    row.innerHTML = `
      <div class="col-6">
        <input name="icd_codes" placeholder="e.g., F84.0" value="${value}" required />
      </div>
      <div class="col-4">
        <input name="icd_desc" placeholder="Description (optional)" />
      </div>
      <div class="col-2">
        <button type="button" class="secondary remove-icd">Remove</button>
      </div>`;
    row.querySelector('.remove-icd').addEventListener('click', () => row.remove());
    return row;
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

  // Initialize with one ICD row
  if (icdList && icdList.children.length === 0) {
    icdList.appendChild(createIcdRow());
  }
  if (addIcdBtn) {
    addIcdBtn.addEventListener('click', () => icdList.appendChild(createIcdRow()));
  }
  if (priorTestsList && priorTestsList.children.length === 0) {
    priorTestsList.appendChild(createPriorTestRow());
  }
  if (addPriorTestBtn) {
    addPriorTestBtn.addEventListener('click', () => priorTestsList.appendChild(createPriorTestRow()));
  }

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
      'dob': 'Date of Birth',
      'member_id': 'Member/Policy ID',
      'provider_name': 'Provider Name',
      'provider_npi': 'Provider NPI',
      'test_type': 'Test Type',
      'icd_codes': 'ICD Codes',
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

    // Check required fields
    required.forEach((el) => {
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

    // Special validation for ICD codes - at least one non-empty ICD code is required
    if (stepEl.querySelector('#icd-list')) {
      const icdInputs = stepEl.querySelectorAll('input[name="icd_codes"]');
      const hasValidIcd = Array.from(icdInputs).some(input => input.value && input.value.trim() !== '');
      if (!hasValidIcd) {
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

  function collectFormData() {
    const data = {};
    const fields = form.querySelectorAll('input, select, textarea');
    const arrFields = new Map();
    fields.forEach((f) => {
      const name = f.name;
      if (!name) return;
      if (f.type === 'checkbox' && f.name === 'cpt_codes') {
        // collect multiple checked CPTs
        arrFields.set('cpt_codes', (arrFields.get('cpt_codes') || []));
        if (f.checked) arrFields.get('cpt_codes').push(f.value);
        return;
      }
      if (name === 'icd_codes' || name === 'icd_desc' || name === 'prior_test_type' || name === 'prior_test_result' || name === 'prior_test_date') {
        arrFields.set(name, (arrFields.get(name) || []));
        arrFields.get(name).push(f.value);
        return;
      }
      if (f.type === 'checkbox') {
        data[name] = f.checked;
      } else {
        data[name] = f.value;
      }
    });
    // Merge array fields
    for (const [k, v] of arrFields.entries()) {
      data[k] = v;
    }
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
      const val = data[name];
      if (typeof val === 'undefined') return;
      if (f.type === 'checkbox') {
        f.checked = !!val;
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

    // ICD rows
    const icds = Array.isArray(data.icd_codes) ? data.icd_codes : [];
    if (icdList) {
      icdList.innerHTML = '';
      if (icds.length === 0) {
        icdList.appendChild(createIcdRow());
      } else {
        icds.forEach((code) => icdList.appendChild(createIcdRow(code)));
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
  }

  async function saveDraft() {
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
        showAlert('error', body?.error || 'Failed to save draft');
      } else {
        showAlert('success', 'Draft saved');
      }
    } catch (err) {
      showAlert('error', 'Network or server error while saving draft');
    }
  }

  // Load draft on page ready
  window.addEventListener('DOMContentLoaded', async () => {
    try {
      const res = await fetch('/draft/load');
      const body = await res.json();
      if (res.ok && body.ok && body.payload) {
        populateForm(body.payload);
        const stepFromServer = parseInt(body.payload.current_step, 10);
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
  });

  // Save Draft button
  if (saveDraftBtn) {
    saveDraftBtn.addEventListener('click', (e) => {
      e.preventDefault();
      saveDraft();
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
      clearError();

      const payload = collectFormData();
      try {
        submitBtn.disabled = true;
        const res = await fetch('/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const body = await res.json();
        if (!res.ok) {
          if (body && body.errors) {
            const msgs = Object.entries(body.errors)
              .map(([k, v]) => `${k}: ${v}`)
              .join('\n');
            showAlert('error', 'Fix the following errors before submitting:\n' + msgs);
          } else {
            showAlert('error', body?.message || 'Submission failed.');
          }
          return;
        }
        showAlert('success', 'Submitted successfully. Reference: ' + (body.file || 'n/a'));
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
