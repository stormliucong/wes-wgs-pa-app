// Simple multi-step form logic with client-side validation and JSON submission
(function () {
  const steps = Array.from(document.querySelectorAll('.form-step'));
  const nextBtns = Array.from(document.querySelectorAll('[data-next]'));
  const prevBtns = Array.from(document.querySelectorAll('[data-prev]'));
  const submitBtn = document.querySelector('#submitBtn');
  const form = document.querySelector('#pa-form');
  const alertBox = document.querySelector('#alert-box');
  const errorsBox = document.querySelector('#form-errors');

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

  let current = 0;
  function showStep(i) {
    steps.forEach((s, idx) => s.classList.toggle('active', idx === i));
    current = i;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  showStep(0);

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
          errorMessages.push(`${el.name} is required`);
        }
      } else if (!el.value || el.value.trim() === '') {
        ok = false;
        errorMessages.push(`${el.labels[0]?.textContent || el.name} is required`);
      }
    });
    
    // Additional format validation for all fields (not just required ones)
    allInputs.forEach((el) => {
      const value = el.value?.trim();
      if (value) { // Only validate if field has a value
        if (el.name === 'provider_npi' || el.name === 'lab_npi') {
          if (!/^\d{10}$/.test(value)) {
            ok = false;
            const fieldLabel = el.labels[0]?.textContent || el.name;
            errorMessages.push(`${fieldLabel} must be exactly 10 digits (numbers only, no spaces or dashes)`);
          }
        }
        // Phone and fax validation - accept formats like (555) 555-5555, 555-555-5555, 555.555.5555, or 5555555555
        if (el.name === 'provider_phone' || el.name === 'provider_fax') {
          // Remove all non-digit characters and check if we have exactly 10 digits
          const digitsOnly = value.replace(/\D/g, '');
          if (!/^\d{10}$/.test(digitsOnly)) {
            ok = false;
            const fieldLabel = el.labels[0]?.textContent || el.name;
            errorMessages.push(`${fieldLabel} must be a valid 10-digit phone number`);
          }
        }
      }
    });
    
    // Show specific error messages if validation fails
    if (!ok && errorMessages.length > 0) {
      showError(errorMessages.join('. '));
    }
    
    return ok;
  }

  nextBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.next, 10);
      if (!validateStep(current)) {
        showError('Please complete required fields before continuing.');
        return;
      }
      clearError();
      showStep(idx);
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

  if (submitBtn) {
    submitBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      if (!validateStep(current)) {
        showError('Please complete required fields before submitting.');
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
