// State management
let state = {
    generatedAds: [],
    smsUsers: [],
    emailUsers: [],
    competitorData: null,
    currentStep: 1,
    selectedAds: [] // Track which ads are selected for sending
};

// Step navigation
function showStep(stepNumber) {
    state.currentStep = stepNumber;
    
    // Hide all steps
    document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
    
    // Show target step
    const targetStep = document.getElementById(`step${stepNumber}`);
    if (targetStep) {
        targetStep.classList.add('active');
    }
    
    // Update progress indicators
    document.querySelectorAll('.step').forEach((el, index) => {
        const stepNum = index + 1;
        if (stepNum < stepNumber) {
            el.classList.add('completed');
            el.classList.remove('active');
        } else if (stepNum === stepNumber) {
            el.classList.add('active');
            el.classList.remove('completed');
        } else {
            el.classList.remove('active', 'completed');
        }
    });
    
    // Update navigation buttons visibility
    updateNavigationButtons();
    
    // If step 4, show summary
    if (stepNumber === 4) {
        showSummary();
    }
}

// Update navigation buttons
function updateNavigationButtons() {
    // Back buttons
    const backToStep1 = document.getElementById('backToStep1');
    const backToStep2 = document.getElementById('backToStep2');
    
    if (backToStep1) backToStep1.style.display = state.currentStep > 1 ? 'inline-block' : 'none';
    if (backToStep2) backToStep2.style.display = state.currentStep > 2 ? 'inline-block' : 'none';
}

// Form validation
function validateForm() {
    const ourBrand = document.getElementById('our_brand').value.trim();
    const competitorName = document.getElementById('competitor_name').value.trim();
    const zipcode = document.getElementById('zipcode').value.trim();
    
    const isValid = ourBrand && competitorName && zipcode;
    
    const generateBtn = document.getElementById('generateBtn');
    if (generateBtn) {
        generateBtn.disabled = !isValid;
        if (!isValid) {
            generateBtn.style.opacity = '0.5';
            generateBtn.style.cursor = 'not-allowed';
        } else {
            generateBtn.style.opacity = '1';
            generateBtn.style.cursor = 'pointer';
        }
    }
    
    return isValid;
}

// Real-time validation
function setupRealTimeValidation() {
    const requiredFields = ['our_brand', 'competitor_name', 'zipcode'];
    
    requiredFields.forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            field.addEventListener('input', () => {
                validateForm();
                validateField(fieldId);
            });
            field.addEventListener('blur', () => validateField(fieldId));
        }
    });
    
    // Phone validation
    const phoneField = document.getElementById('smsPhone');
    if (phoneField) {
        phoneField.addEventListener('input', debounce(validatePhoneField, 500));
        phoneField.addEventListener('blur', validatePhoneField);
    }
    
    // Email validation
    const emailField = document.getElementById('emailAddress');
    if (emailField) {
        emailField.addEventListener('input', debounce(validateEmailField, 500));
        emailField.addEventListener('blur', validateEmailField);
    }
}

// Validate individual field
function validateField(fieldId) {
    const field = document.getElementById(fieldId);
    if (!field) return;
    
    const value = field.value.trim();
    let isValid = true;
    let errorMsg = '';
    
    if (field.required && !value) {
        isValid = false;
        errorMsg = 'This field is required';
    } else if (fieldId === 'zipcode' && value && !/^\d{5}$/.test(value)) {
        isValid = false;
        errorMsg = 'ZIP code must be 5 digits';
    }
    
    // Show/hide error
    let errorElement = field.parentElement.querySelector('.field-error');
    if (!errorElement && !isValid) {
        errorElement = document.createElement('small');
        errorElement.className = 'field-error';
        field.parentElement.appendChild(errorElement);
    }
    
    if (errorElement) {
        if (isValid) {
            errorElement.remove();
            field.style.borderColor = '#dee2e6';
        } else {
            errorElement.textContent = errorMsg;
            errorElement.style.color = '#dc3545';
            field.style.borderColor = '#dc3545';
        }
    }
    
    return isValid;
}

// Validate phone field
async function validatePhoneField() {
    const phoneField = document.getElementById('smsPhone');
    if (!phoneField) return;
    
    const phone = phoneField.value.trim();
    if (!phone) {
        phoneField.style.borderColor = '#dee2e6';
        return;
    }
    
    try {
        const response = await fetch('/api/validate/phone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone })
        });
        
        const result = await response.json();
        
        if (result.valid) {
            phoneField.style.borderColor = '#28a745';
        } else {
            phoneField.style.borderColor = '#dc3545';
        }
    } catch (error) {
        // Silent fail for validation
    }
}

// Validate email field
async function validateEmailField() {
    const emailField = document.getElementById('emailAddress');
    if (!emailField) return;
    
    const email = emailField.value.trim();
    if (!email) {
        emailField.style.borderColor = '#dee2e6';
        return;
    }
    
    try {
        const response = await fetch('/api/validate/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        
        const result = await response.json();
        
        if (result.valid) {
            emailField.style.borderColor = '#28a745';
        } else {
            emailField.style.borderColor = '#dc3545';
        }
    } catch (error) {
        // Silent fail for validation
    }
}

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Show button loader
function showButtonLoader(buttonId) {
    const btn = document.getElementById(buttonId);
    if (btn) {
        const btnText = btn.querySelector('.btn-text');
        const btnLoader = btn.querySelector('.btn-loader');
        if (btnText) btnText.style.display = 'none';
        if (btnLoader) btnLoader.style.display = 'inline-block';
        btn.disabled = true;
    }
}

// Hide button loader
function hideButtonLoader(buttonId) {
    const btn = document.getElementById(buttonId);
    if (btn) {
        const btnText = btn.querySelector('.btn-text');
        const btnLoader = btn.querySelector('.btn-loader');
        if (btnText) btnText.style.display = 'inline-block';
        if (btnLoader) btnLoader.style.display = 'none';
        btn.disabled = false;
    }
}

// Poll job status
async function pollJobStatus(jobId, onComplete, onError) {
    const maxAttempts = 60; // Poll for up to 5 minutes (5s * 60) - max polling time
    let attempts = 0;
    
    const poll = async () => {
        try {
            const response = await fetch(`/api/job/${jobId}`);
            const result = await response.json();
            
            if (result.success && result.job) {
                const job = result.job;
                
                if (job.status === 'finished') {
                    onComplete(job.result);
                } else if (job.status === 'failed') {
                    onError(job.error || 'Job failed');
                } else if (attempts >= maxAttempts) {
                    onError('Job timeout - please try again');
                } else {
                    // Continue polling
                    attempts++;
                    setTimeout(poll, 5000); // Poll every 5 seconds
                }
            } else {
                onError(result.error || 'Failed to check job status');
            }
        } catch (error) {
            onError(error.message);
        }
    };
    
    poll();
}

// Competitor form submission
document.getElementById('competitorForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    if (!validateForm()) {
        return;
    }
    
    const formData = new FormData(e.target);
    const data = {
        our_brand: formData.get('our_brand'),
        competitor_name: formData.get('competitor_name'),
        ad_copy: formData.get('ad_copy'),
        location: formData.get('location'),
        zipcode: formData.get('zipcode'),
        hashtags: formData.get('hashtags') ? formData.get('hashtags').split(',').map(t => t.trim()).filter(t => t) : [],
        industry: formData.get('industry') || null,
        audience_type: formData.get('audience_type') || null,
        offer_type: formData.get('offer_type') || null,
        goal: formData.get('goal') || null,
        num_variations: parseInt(formData.get('num_variations') || '3', 10)
    };
    
    // Show step 2
    showStep(2);
    
    // Show loading
    const adsContainer = document.getElementById('adsContainer');
    adsContainer.innerHTML = '<div class="loading"><div class="spinner"></div>Generating ads with AI... Please wait.</div>';
    
    // Show loader on button
    showButtonLoader('generateBtn');
    
    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (result.job_id) {
                // Background job - poll for status
                pollJobStatus(
                    result.job_id,
                    (jobResult) => {
                        if (jobResult.success) {
                            state.generatedAds = jobResult.ads;
                            state.competitorData = data;
                            displayAds(jobResult.ads);
                        } else {
                            adsContainer.innerHTML = `<div class="result-error">Error: ${jobResult.error}</div>`;
                        }
                        hideButtonLoader('generateBtn');
                    },
                    (error) => {
                        adsContainer.innerHTML = `<div class="result-error">Error: ${error}</div>`;
                        hideButtonLoader('generateBtn');
                    }
                );
            } else {
                // Synchronous result
                state.generatedAds = result.ads;
                state.competitorData = data;
                displayAds(result.ads);
                hideButtonLoader('generateBtn');
            }
        } else {
            adsContainer.innerHTML = `<div class="result-error">Error: ${result.error}</div>`;
            hideButtonLoader('generateBtn');
        }
    } catch (error) {
        adsContainer.innerHTML = `<div class="result-error">Error: ${error.message}</div>`;
        hideButtonLoader('generateBtn');
    }
});

// Display generated ads with copy and edit options
function displayAds(ads) {
    const adsContainer = document.getElementById('adsContainer');
    
    if (ads.length === 0) {
        adsContainer.innerHTML = '<div class="result-error">No ads generated. Please try again.</div>';
        return;
    }
    
    // Group ads into sets (3 ads per set)
    const adsPerSet = 3;
    const adSets = [];
    for (let i = 0; i < ads.length; i += adsPerSet) {
        adSets.push(ads.slice(i, i + adsPerSet));
    }
    
    let html = '';
    
    adSets.forEach((adSet, setIndex) => {
        html += `<div class="ad-set" data-set-index="${setIndex}">`;
        html += `<div class="ad-set-header">`;
        html += `<h3>Ad Set ${setIndex + 1}</h3>`;
        html += `<button class="btn btn-secondary btn-sm" onclick="regenerateAdSet(${setIndex})">🔄 Regenerate</button>`;
        html += `</div>`;
        
        adSet.forEach((ad, adIndex) => {
            const globalIndex = setIndex * adsPerSet + adIndex;
            const isSelected = state.selectedAds.includes(globalIndex);
            html += `
                <div class="ad-card ${isSelected ? 'ad-selected' : ''}" data-ad-index="${globalIndex}">
                    <div class="ad-header">
                        <div class="ad-title-group">
                            <label class="ad-checkbox-label">
                                <input type="checkbox" 
                                       class="ad-checkbox" 
                                       ${isSelected ? 'checked' : ''}
                                       onchange="toggleAdSelection(${globalIndex})"
                                       id="ad-checkbox-${globalIndex}">
                                <span class="checkbox-custom"></span>
                                <h4>Ad ${globalIndex + 1}</h4>
                            </label>
                        </div>
                        <div class="ad-actions">
                            <button class="btn-icon" onclick="copyAd(${globalIndex})" title="Copy ad">
                                📋 Copy
                            </button>
                            <button class="btn-icon" onclick="editAd(${globalIndex})" title="Edit ad">
                                ✏️ Edit
                            </button>
                            <button class="btn-icon" onclick="showAdPreview(${globalIndex}, 'sms')" title="SMS Preview">
                                📱 SMS
                            </button>
                            <button class="btn-icon" onclick="showAdPreview(${globalIndex}, 'email')" title="Email Preview">
                                📧 Email
                            </button>
                            <button class="btn-icon" onclick="saveAdAsTemplate(${globalIndex})" title="Save as Template">
                                💾 Template
                            </button>
                        </div>
                    </div>
                    <div class="ad-content">
                        <div class="ad-headline" id="headline-${globalIndex}">${escapeHtml(ad.headline)}</div>
                        <div class="ad-body" id="adtext-${globalIndex}">${escapeHtml(ad.ad_text)}</div>
                        <div class="ad-cta" id="cta-${globalIndex}">
                            <span class="cta-button">${escapeHtml(ad.cta)}</span>
                        </div>
                        <div class="ad-hashtags">
                            ${ad.hashtags.map(tag => `<span class="hashtag">${escapeHtml(tag)}</span>`).join('')}
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += `</div>`;
    });
    
    adsContainer.innerHTML = html;
    
    // Clear and re-initialize selected ads
    state.selectedAds = [];
    
    // Auto-select all ads by default
    state.selectedAds = ads.map((_, index) => index);
    
    // Update all checkboxes to reflect the selection
    ads.forEach((_, index) => {
        const checkbox = document.getElementById(`ad-checkbox-${index}`);
        if (checkbox) {
            checkbox.checked = true;
        }
    });
    
    // Show selection info and continue button
    updateAdSelectionInfo();
    document.getElementById('continueToUsers').style.display = 'block';
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toggle ad selection
function toggleAdSelection(adIndex) {
    const checkbox = document.getElementById(`ad-checkbox-${adIndex}`);
    const adCard = document.querySelector(`.ad-card[data-ad-index="${adIndex}"]`);
    
    if (checkbox && checkbox.checked) {
        // Add to selected
        if (!state.selectedAds.includes(adIndex)) {
            state.selectedAds.push(adIndex);
        }
        if (adCard) {
            adCard.classList.add('ad-selected');
        }
    } else {
        // Remove from selected
        const indexInArray = state.selectedAds.indexOf(adIndex);
        if (indexInArray > -1) {
            state.selectedAds.splice(indexInArray, 1);
        }
        if (adCard) {
            adCard.classList.remove('ad-selected');
        }
    }
    
    console.log('Selected ads:', state.selectedAds); // Debug log
    updateAdSelectionInfo();
}

// Update ad selection info
function updateAdSelectionInfo() {
    const selectedCount = state.selectedAds.length;
    const totalCount = state.generatedAds.length;
    
    // Update or create selection info banner
    let infoBanner = document.getElementById('adSelectionInfo');
    if (!infoBanner) {
        infoBanner = document.createElement('div');
        infoBanner.id = 'adSelectionInfo';
        infoBanner.className = 'ad-selection-info';
        const adsContainer = document.getElementById('adsContainer');
        adsContainer.insertBefore(infoBanner, adsContainer.firstChild);
    }
    
    if (selectedCount === 0) {
        infoBanner.innerHTML = `
            <div class="selection-warning">
                ⚠️ No ads selected. Please select at least one ad to continue.
            </div>
        `;
        infoBanner.style.display = 'block';
        document.getElementById('continueToUsers').style.display = 'none';
    } else {
        infoBanner.innerHTML = `
            <div class="selection-info-content">
                <span class="selection-count">
                    <strong>${selectedCount}</strong> of ${totalCount} ad${selectedCount !== 1 ? 's' : ''} selected
                </span>
                <div class="selection-actions">
                    <button class="btn-link" onclick="selectAllAds()">Select All</button>
                    <button class="btn-link" onclick="deselectAllAds()">Deselect All</button>
                </div>
            </div>
        `;
        infoBanner.style.display = 'block';
        document.getElementById('continueToUsers').style.display = 'block';
    }
}

// Select all ads
function selectAllAds() {
    state.selectedAds = state.generatedAds.map((_, index) => index);
    
    // Update checkboxes and cards
    state.generatedAds.forEach((_, index) => {
        const checkbox = document.getElementById(`ad-checkbox-${index}`);
        const adCard = document.querySelector(`.ad-card[data-ad-index="${index}"]`);
        if (checkbox) checkbox.checked = true;
        if (adCard) adCard.classList.add('ad-selected');
    });
    
    updateAdSelectionInfo();
    showNotification('All ads selected', 'success');
}

// Deselect all ads
function deselectAllAds() {
    state.selectedAds = [];
    
    // Update checkboxes and cards
    state.generatedAds.forEach((_, index) => {
        const checkbox = document.getElementById(`ad-checkbox-${index}`);
        const adCard = document.querySelector(`.ad-card[data-ad-index="${index}"]`);
        if (checkbox) checkbox.checked = false;
        if (adCard) adCard.classList.remove('ad-selected');
    });
    
    updateAdSelectionInfo();
    showNotification('All ads deselected', 'info');
}

// Copy ad to clipboard
async function copyAd(adIndex) {
    const ad = state.generatedAds[adIndex];
    if (!ad) return;
    
    // Format without labels for cleaner copy
    const adText = `${ad.headline}\n\n${ad.ad_text}\n\n${ad.cta}\n\n${ad.hashtags.join(' ')}`;
    
    try {
        await navigator.clipboard.writeText(adText);
        showNotification('Ad copied to clipboard!', 'success');
    } catch (error) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = adText;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showNotification('Ad copied to clipboard!', 'success');
    }
}

// Edit ad
function editAd(adIndex) {
    const ad = state.generatedAds[adIndex];
    if (!ad) return;
    
    const headlineEl = document.getElementById(`headline-${adIndex}`);
    const adTextEl = document.getElementById(`adtext-${adIndex}`);
    const ctaEl = document.getElementById(`cta-${adIndex}`);
    
    // Convert to editable fields
    if (headlineEl && !headlineEl.querySelector('input')) {
        const currentValue = ad.headline;
        headlineEl.innerHTML = `<input type="text" value="${escapeHtml(currentValue)}" class="ad-edit-input" onblur="saveAdEdit(${adIndex}, 'headline', this.value)" style="font-size: 1.5em; font-weight: bold;">`;
        headlineEl.querySelector('input').focus();
    }
    if (adTextEl && !adTextEl.querySelector('textarea')) {
        const currentValue = ad.ad_text;
        adTextEl.innerHTML = `<textarea class="ad-edit-textarea" onblur="saveAdEdit(${adIndex}, 'ad_text', this.value)" style="font-size: 1em; line-height: 1.6;">${escapeHtml(currentValue)}</textarea>`;
    }
    if (ctaEl && !ctaEl.querySelector('input')) {
        const currentValue = ad.cta;
        ctaEl.innerHTML = `<input type="text" value="${escapeHtml(currentValue)}" class="ad-edit-input" onblur="saveAdEdit(${adIndex}, 'cta', this.value)" style="font-weight: 600;">`;
    }
}

// Save ad edit
function saveAdEdit(adIndex, field, value) {
    if (!state.generatedAds[adIndex]) return;
    
    if (field === 'headline') {
        state.generatedAds[adIndex].headline = value;
        document.getElementById(`headline-${adIndex}`).innerHTML = escapeHtml(value);
    } else if (field === 'ad_text') {
        state.generatedAds[adIndex].ad_text = value;
        document.getElementById(`adtext-${adIndex}`).innerHTML = escapeHtml(value);
    } else if (field === 'cta') {
        state.generatedAds[adIndex].cta = value;
        const ctaEl = document.getElementById(`cta-${adIndex}`);
        ctaEl.innerHTML = `<span class="cta-button">${escapeHtml(value)}</span>`;
    }
    
    showNotification('Ad updated!', 'success');
}

// Regenerate ad set
async function regenerateAdSet(setIndex) {
    if (!state.competitorData) {
        showNotification('No competitor data available', 'error');
        return;
    }
    
    const adSetElement = document.querySelector(`.ad-set[data-set-index="${setIndex}"]`);
    if (adSetElement) {
        adSetElement.style.opacity = '0.5';
        adSetElement.style.pointerEvents = 'none';
    }
    
    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(state.competitorData)
        });
        
        const result = await response.json();
        
        if (result.success && result.ads.length > 0) {
            // Replace ads in this set
            const adsPerSet = 3;
            const startIndex = setIndex * adsPerSet;
            const endIndex = Math.min(startIndex + adsPerSet, result.ads.length);
            
            for (let i = startIndex; i < endIndex && i < result.ads.length; i++) {
                state.generatedAds[i] = result.ads[i - startIndex];
            }
            
            displayAds(state.generatedAds);
            showNotification('Ad set regenerated!', 'success');
        } else {
            showNotification('Failed to regenerate ads', 'error');
        }
    } catch (error) {
        showNotification('Error regenerating ads: ' + error.message, 'error');
    } finally {
        if (adSetElement) {
            adSetElement.style.opacity = '1';
            adSetElement.style.pointerEvents = 'auto';
        }
    }
}

// Show notification
function showNotification(message, type = 'info') {
    // Remove existing notification
    const existing = document.querySelector('.notification');
    if (existing) existing.remove();
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Navigation handlers
document.getElementById('backToStep1')?.addEventListener('click', () => showStep(1));
document.getElementById('backToStep2')?.addEventListener('click', () => showStep(2));

// Continue to users step
document.getElementById('continueToUsers')?.addEventListener('click', () => {
    showStep(3);
    updateUserSummary();
});

// Continue to step 4
document.getElementById('continueToStep4')?.addEventListener('click', () => {
    if (state.smsUsers.length === 0 && state.emailUsers.length === 0) {
        showNotification('Please add at least one phone number or email address', 'error');
        return;
    }
    showStep(4);
});

// Toggle SMS tags input
function toggleSMSTags() {
    const tagsInput = document.getElementById('smsTags');
    if (tagsInput) {
        tagsInput.style.display = tagsInput.style.display === 'none' ? 'block' : 'none';
    }
}

// Toggle Email tags input
function toggleEmailTags() {
    const tagsInput = document.getElementById('emailTags');
    if (tagsInput) {
        tagsInput.style.display = tagsInput.style.display === 'none' ? 'block' : 'none';
    }
}

// Add SMS user
async function addSMSUser() {
    const nameInput = document.getElementById('smsName');
    const phoneInput = document.getElementById('smsPhone');
    const tagsInput = document.getElementById('smsTags');
    
    const name = nameInput.value.trim();
    const phone = phoneInput.value.trim();
    const tags = tagsInput && tagsInput.value.trim() ? tagsInput.value.split(',').map(t => t.trim()).filter(t => t) : [];
    
    if (!phone) {
        showNotification('Please enter a phone number', 'error');
        return;
    }
    
    // Validate phone
    try {
        const response = await fetch('/api/validate/phone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone })
        });
        
        const result = await response.json();
        
        if (!result.valid) {
            showNotification('Invalid phone number format. Please use format: +1234567890', 'error');
            return;
        }
        
        const normalizedPhone = result.normalized;
        
        // Check for duplicates
        if (state.smsUsers.some(u => u.phone === normalizedPhone)) {
            showNotification('This phone number is already added', 'error');
            return;
        }
        
        state.smsUsers.push({
            name: name || `User ${state.smsUsers.length + 1}`,
            phone: normalizedPhone,
            tags: tags
        });
        
        nameInput.value = '';
        phoneInput.value = '';
        if (tagsInput) tagsInput.value = '';
        phoneInput.style.borderColor = '#dee2e6';
        
        updateSMSUsersList();
        updateUserSummary();
        showNotification('Phone number added!', 'success');
    } catch (error) {
        showNotification('Error validating phone number: ' + error.message, 'error');
    }
}

// Add Email user
async function addEmailUser() {
    const nameInput = document.getElementById('emailName');
    const emailInput = document.getElementById('emailAddress');
    const tagsInput = document.getElementById('emailTags');
    
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    const tags = tagsInput && tagsInput.value.trim() ? tagsInput.value.split(',').map(t => t.trim()).filter(t => t) : [];
    
    if (!email) {
        showNotification('Please enter an email address', 'error');
        return;
    }
    
    // Validate email
    try {
        const response = await fetch('/api/validate/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        
        const result = await response.json();
        
        if (!result.valid) {
            showNotification('Invalid email format. Please enter a valid email address.', 'error');
            return;
        }
        
        const normalizedEmail = email.toLowerCase();
        
        // Check for duplicates
        if (state.emailUsers.some(u => u.email === normalizedEmail)) {
            showNotification('This email address is already added', 'error');
            return;
        }
        
        state.emailUsers.push({
            name: name || `User ${state.emailUsers.length + 1}`,
            email: normalizedEmail,
            tags: tags
        });
        
        nameInput.value = '';
        emailInput.value = '';
        if (tagsInput) tagsInput.value = '';
        emailInput.style.borderColor = '#dee2e6';
        
        updateEmailUsersList();
        updateUserSummary();
        showNotification('Email address added!', 'success');
    } catch (error) {
        showNotification('Error validating email: ' + error.message, 'error');
    }
}

// Update SMS users list with table
function updateSMSUsersList() {
    const list = document.getElementById('smsUsersList');
    
    if (state.smsUsers.length === 0) {
        list.innerHTML = '<p style="color: #6c757d; text-align: center; padding: 20px;">No phone numbers added yet</p>';
        return;
    }
    
    let html = '<table class="users-table"><thead><tr><th>Name</th><th>Phone</th><th>Tags</th><th>Status</th><th>Action</th></tr></thead><tbody>';
    
    state.smsUsers.forEach((user, index) => {
        const tags = user.tags && user.tags.length > 0 ? user.tags.map(t => `<span style="background: #e3f2fd; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin-right: 4px;">${escapeHtml(t)}</span>`).join('') : '-';
        html += `
            <tr>
                <td>${escapeHtml(user.name)}</td>
                <td>${escapeHtml(user.phone)}</td>
                <td>${tags}</td>
                <td><span class="status-badge status-ready">Ready</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="removeSMSUser(${index})">Remove</button></td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    list.innerHTML = html;
}

// Update Email users list with table
function updateEmailUsersList() {
    const list = document.getElementById('emailUsersList');
    
    if (state.emailUsers.length === 0) {
        list.innerHTML = '<p style="color: #6c757d; text-align: center; padding: 20px;">No email addresses added yet</p>';
        return;
    }
    
    let html = '<table class="users-table"><thead><tr><th>Name</th><th>Email</th><th>Tags</th><th>Status</th><th>Action</th></tr></thead><tbody>';
    
    state.emailUsers.forEach((user, index) => {
        const tags = user.tags && user.tags.length > 0 ? user.tags.map(t => `<span style="background: #e3f2fd; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; margin-right: 4px;">${escapeHtml(t)}</span>`).join('') : '-';
        html += `
            <tr>
                <td>${escapeHtml(user.name)}</td>
                <td>${escapeHtml(user.email)}</td>
                <td>${tags}</td>
                <td><span class="status-badge status-ready">Ready</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="removeEmailUser(${index})">Remove</button></td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    list.innerHTML = html;
}

// Remove SMS user
function removeSMSUser(index) {
    state.smsUsers.splice(index, 1);
    updateSMSUsersList();
    updateUserSummary();
    showNotification('Phone number removed', 'info');
}

// Remove Email user
function removeEmailUser(index) {
    state.emailUsers.splice(index, 1);
    updateEmailUsersList();
    updateUserSummary();
    showNotification('Email address removed', 'info');
}

// Update user summary
function updateUserSummary() {
    const smsCount = state.smsUsers.length;
    const emailCount = state.emailUsers.length;
    const totalCount = smsCount + emailCount;
    
    document.getElementById('smsCount').textContent = smsCount;
    document.getElementById('emailCount').textContent = emailCount;
    document.getElementById('totalCount').textContent = totalCount;
    
    // Enable/disable continue button
    const continueBtn = document.getElementById('continueToStep4');
    if (continueBtn) {
        continueBtn.disabled = totalCount === 0;
        if (totalCount === 0) {
            continueBtn.style.opacity = '0.5';
            continueBtn.style.cursor = 'not-allowed';
        } else {
            continueBtn.style.opacity = '1';
            continueBtn.style.cursor = 'pointer';
        }
    }
}

// Bulk import functions
function showBulkSMSImport() {
    document.getElementById('bulkSMSImport').style.display = 'block';
}

function hideBulkSMSImport() {
    document.getElementById('bulkSMSImport').style.display = 'none';
    document.getElementById('bulkSMSInput').value = '';
}

function showBulkEmailImport() {
    document.getElementById('bulkEmailImport').style.display = 'block';
}

function hideBulkEmailImport() {
    document.getElementById('bulkEmailImport').style.display = 'none';
    document.getElementById('bulkEmailInput').value = '';
}

// Process bulk SMS import
async function processBulkSMS() {
    const input = document.getElementById('bulkSMSInput').value.trim();
    if (!input) {
        showNotification('Please enter phone numbers', 'error');
        return;
    }
    
    // Parse input (support multiple formats)
    const lines = input.split('\n').map(l => l.trim()).filter(l => l);
    const phones = [];
    
    for (const line of lines) {
        // Check if CSV format (Name, Phone)
        if (line.includes(',')) {
            const parts = line.split(',').map(p => p.trim());
            if (parts.length >= 2) {
                phones.push({ name: parts[0], phone: parts[1] });
            } else if (parts.length === 1) {
                phones.push({ name: '', phone: parts[0] });
            }
        } else {
            // Single phone number
            phones.push({ name: '', phone: line });
        }
    }
    
    if (phones.length === 0) {
        showNotification('No valid phone numbers found', 'error');
        return;
    }
    
    // Validate and add phones
    let added = 0;
    let skipped = 0;
    
    for (const item of phones) {
        const phone = item.phone.trim();
        if (!phone) continue;
        
        try {
            const response = await fetch('/api/validate/phone', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone })
            });
            
            const result = await response.json();
            
        if (result.valid) {
            const normalizedPhone = result.normalized;
            
            // Check for duplicates
            if (!state.smsUsers.some(u => u.phone === normalizedPhone)) {
                state.smsUsers.push({
                    name: item.name || `User ${state.smsUsers.length + 1}`,
                    phone: normalizedPhone,
                    tags: item.tags || []
                });
                added++;
            } else {
                skipped++;
            }
            } else {
                skipped++;
            }
        } catch (error) {
            skipped++;
        }
    }
    
    updateSMSUsersList();
    updateUserSummary();
    hideBulkSMSImport();
    
    showNotification(`Added ${added} phone number(s)${skipped > 0 ? `, skipped ${skipped} invalid/duplicate` : ''}`, added > 0 ? 'success' : 'error');
}

// Process bulk email import
async function processBulkEmail() {
    const input = document.getElementById('bulkEmailInput').value.trim();
    if (!input) {
        showNotification('Please enter email addresses', 'error');
        return;
    }
    
    // Parse input (support multiple formats)
    const lines = input.split('\n').map(l => l.trim()).filter(l => l);
    const emails = [];
    
    for (const line of lines) {
        // Check if CSV format (Name, Email)
        if (line.includes(',')) {
            const parts = line.split(',').map(p => p.trim());
            if (parts.length >= 2) {
                emails.push({ name: parts[0], email: parts[1] });
            } else if (parts.length === 1) {
                emails.push({ name: '', email: parts[0] });
            }
        } else {
            // Single email
            emails.push({ name: '', email: line });
        }
    }
    
    if (emails.length === 0) {
        showNotification('No valid email addresses found', 'error');
        return;
    }
    
    // Validate and add emails
    let added = 0;
    let skipped = 0;
    
    for (const item of emails) {
        const email = item.email.trim().toLowerCase();
        if (!email) continue;
        
        try {
            const response = await fetch('/api/validate/email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            
            const result = await response.json();
            
            if (result.valid) {
                // Check for duplicates
                if (!state.emailUsers.some(u => u.email === email)) {
                    state.emailUsers.push({
                        name: item.name || `User ${state.emailUsers.length + 1}`,
                        email: email,
                        tags: item.tags || []
                    });
                    added++;
                } else {
                    skipped++;
                }
            } else {
                skipped++;
            }
        } catch (error) {
            skipped++;
        }
    }
    
    updateEmailUsersList();
    updateUserSummary();
    hideBulkEmailImport();
    
    showNotification(`Added ${added} email address(es)${skipped > 0 ? `, skipped ${skipped} invalid/duplicate` : ''}`, added > 0 ? 'success' : 'error');
}

// Handle CSV file upload for SMS
async function handleSMSFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const text = await file.text();
    document.getElementById('bulkSMSInput').value = text;
}

// Handle CSV file upload for Email
async function handleEmailFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const text = await file.text();
    document.getElementById('bulkEmailInput').value = text;
}

// Show summary in step 4
function showSummary() {
    const summaryContainer = document.getElementById('summaryContainer');
    const smsCount = state.smsUsers.length;
    const emailCount = state.emailUsers.length;
    const channels = (smsCount > 0 ? 1 : 0) + (emailCount > 0 ? 1 : 0);
    const selectedAdCount = state.selectedAds.length;
    
    document.getElementById('summaryTotalSMS').textContent = smsCount;
    document.getElementById('summaryTotalEmail').textContent = emailCount;
    document.getElementById('summaryChannels').textContent = channels;
    document.getElementById('summaryTotalAds').textContent = selectedAdCount;
    
    summaryContainer.style.display = 'block';
}

// Show campaign preview
function showCampaignPreview() {
    const selectedAdsData = state.selectedAds.map(index => state.generatedAds[index]);
    const totalRecipients = state.smsUsers.length + state.emailUsers.length;
    
    let previewHTML = `
        <div style="max-width: 800px; margin: 0 auto;">
            <h3>Campaign Preview</h3>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <p><strong>Ads:</strong> ${selectedAdsData.length} variation(s)</p>
                <p><strong>Recipients:</strong> ${totalRecipients} total (${state.smsUsers.length} SMS, ${state.emailUsers.length} Email)</p>
            </div>
            <div style="max-height: 400px; overflow-y: auto;">
                ${selectedAdsData.map((ad, idx) => `
                    <div style="border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; border-radius: 5px;">
                        <h4>Ad ${idx + 1}</h4>
                        <p><strong>Headline:</strong> ${escapeHtml(ad.headline)}</p>
                        <p><strong>Body:</strong> ${escapeHtml(ad.ad_text)}</p>
                        <p><strong>CTA:</strong> ${escapeHtml(ad.cta)}</p>
                        <p><strong>Hashtags:</strong> ${ad.hashtags.map(t => escapeHtml(t)).join(', ')}</p>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); z-index: 10000; display: flex; align-items: center; justify-content: center; overflow-y: auto; padding: 20px; backdrop-filter: blur(4px);';
    
    const closeModal = () => {
        modal.style.opacity = '0';
        setTimeout(() => modal.remove(), 300);
    };
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
    
    modal.innerHTML = `
        <div class="modal-content" style="background: white; padding: 0; border-radius: 16px; max-width: 900px; width: 100%; position: relative; margin: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-height: 90vh; overflow: hidden; display: flex; flex-direction: column;">
            <div style="padding: 24px 30px; border-bottom: 2px solid #e9ecef; display: flex; justify-content: space-between; align-items: center; background: #fff;">
                <h3 style="margin: 0; color: #ff6600; font-size: 1.5em; font-weight: bold;">Campaign Preview</h3>
                <button class="modal-close-btn" onclick="arguments[0].target.closest('.modal-overlay').remove()" style="position: relative; top: 0; right: 0; background: #f8f9fa; border: 2px solid #dee2e6; border-radius: 50%; width: 36px; height: 36px; font-size: 20px; cursor: pointer; display: flex; align-items: center; justify-content: center; color: #6c757d; transition: all 0.2s; line-height: 1; padding: 0;">&times;</button>
            </div>
            <div style="padding: 30px; overflow-y: auto; flex: 1;">
                ${previewHTML}
            </div>
        </div>
    `;
    
    // Add click handler to close button
    setTimeout(() => {
        const closeBtn = modal.querySelector('.modal-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeModal);
            closeBtn.addEventListener('mouseenter', () => {
                closeBtn.style.background = '#ff6600';
                closeBtn.style.borderColor = '#ff6600';
                closeBtn.style.color = 'white';
            });
            closeBtn.addEventListener('mouseleave', () => {
                closeBtn.style.background = '#f8f9fa';
                closeBtn.style.borderColor = '#dee2e6';
                closeBtn.style.color = '#6c757d';
            });
        }
    }, 10);
    
    document.body.appendChild(modal);
    
    // Animate in
    setTimeout(() => {
        modal.style.opacity = '1';
    }, 10);
}

// Show schedule dialog
function showScheduleDialog() {
    const dialog = document.getElementById('scheduleDialog');
    if (dialog) {
        dialog.style.display = 'flex';
        // Set minimum date to today
        const dateInput = document.getElementById('scheduleDate');
        if (dateInput) {
            dateInput.min = new Date().toISOString().split('T')[0];
        }
        // Set default timezone to user's timezone
        const timezoneInput = document.getElementById('scheduleTimezone');
        if (timezoneInput && !timezoneInput.value) {
            try {
                const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                // Try to find matching option
                const options = Array.from(timezoneInput.options);
                const matchingOption = options.find(opt => opt.value === userTimezone);
                if (matchingOption) {
                    timezoneInput.value = userTimezone;
                } else {
                    // Set to UTC as fallback
                    timezoneInput.value = 'UTC';
                }
            } catch (e) {
                timezoneInput.value = 'UTC';
            }
        }
    }
}

// Hide schedule dialog
function hideScheduleDialog() {
    const dialog = document.getElementById('scheduleDialog');
    if (dialog) dialog.style.display = 'none';
}

// Confirm and send ads
function confirmAndSendAds(when) {
    const selectedAdsData = state.selectedAds.map(index => state.generatedAds[index]);
    const totalRecipients = state.smsUsers.length + state.emailUsers.length;
    const channels = [];
    if (state.smsUsers.length > 0) channels.push(`SMS (${state.smsUsers.length})`);
    if (state.emailUsers.length > 0) channels.push(`Email (${state.emailUsers.length})`);
    
    let scheduleInfo = '';
    if (when === 'scheduled') {
        const dateInput = document.getElementById('scheduleDate');
        const timeInput = document.getElementById('scheduleTime');
        const timezoneInput = document.getElementById('scheduleTimezone');
        if (!dateInput || !dateInput.value || !timeInput || !timeInput.value || !timezoneInput || !timezoneInput.value) {
            showNotification('Please select date, time, and timezone', 'error');
            return;
        }
        const timezoneName = timezoneInput.options[timezoneInput.selectedIndex].text;
        scheduleInfo = `\nScheduled for: ${dateInput.value} at ${timeInput.value} (${timezoneName})`;
    }
    
    const message = `Confirm sending campaign?\n\n` +
        `Ads: ${selectedAdsData.length} variation(s)\n` +
        `Recipients: ${totalRecipients} total\n` +
        `Channels: ${channels.join(', ')}${scheduleInfo}`;
    
    if (confirm(message)) {
        if (when === 'scheduled') {
            // Store scheduled job (in production, save to backend)
            showNotification('Campaign scheduled! (Note: In production, this would be saved to backend)', 'success');
            hideScheduleDialog();
        } else {
            sendAds();
        }
    }
}

// Send ads
async function sendAds() {
    if (state.smsUsers.length === 0 && state.emailUsers.length === 0) {
        showNotification('Please add at least one phone number or email address', 'error');
        return;
    }
    
    if (state.selectedAds.length === 0) {
        showNotification('Please select at least one ad to send', 'error');
        return;
    }
    
    // Hide summary, show sending
    const summaryContainer = document.getElementById('summaryContainer');
    if (summaryContainer) summaryContainer.style.display = 'none';
    
    const resultsContainer = document.getElementById('sendingResults');
    if (resultsContainer) {
        resultsContainer.innerHTML = '<div class="loading"><div class="spinner"></div>Sending ads... Please wait.</div>';
        resultsContainer.style.display = 'block';
    }
    
    // Show loader
    showButtonLoader('sendAdsNowBtn');
    
    // Get only selected ads
    const selectedAdsData = state.selectedAds.map(index => state.generatedAds[index]);
    
    try {
        const response = await fetch('/api/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                sms_users: state.smsUsers,
                email_users: state.emailUsers,
                ads: selectedAdsData
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (result.job_id) {
                // Background job - poll for status
                pollJobStatus(
                    result.job_id,
                    (jobResult) => {
                        if (jobResult.success) {
                            displayResults(jobResult.results);
                        } else {
                            if (resultsContainer) {
                                resultsContainer.innerHTML = `<div class="result-error">Error: ${jobResult.error}</div>`;
                            }
                        }
                        const resultsNav = document.getElementById('resultsNavigation');
                        if (resultsNav) resultsNav.style.display = 'block';
                        hideButtonLoader('sendAdsNowBtn');
                    },
                    (error) => {
                        if (resultsContainer) {
                            resultsContainer.innerHTML = `<div class="result-error">Error: ${error}</div>`;
                        }
                        hideButtonLoader('sendAdsNowBtn');
                    }
                );
            } else {
                // Synchronous result
                displayResults(result.results);
                const resultsNav = document.getElementById('resultsNavigation');
                if (resultsNav) resultsNav.style.display = 'block';
                hideButtonLoader('sendAdsNowBtn');
            }
        } else {
            if (resultsContainer) {
                resultsContainer.innerHTML = `<div class="result-error">Error: ${result.error}</div>`;
            }
            hideButtonLoader('sendAdsNowBtn');
        }
    } catch (error) {
        if (resultsContainer) {
            resultsContainer.innerHTML = `<div class="result-error">Error: ${error.message}</div>`;
        }
        hideButtonLoader('sendAdsNowBtn');
    }
}

// Display results
function displayResults(results) {
    const resultsContainer = document.getElementById('sendingResults');
    if (!resultsContainer) return;
    
    const summary = results.summary;
    const errorMessages = summary.error_messages || [];
    const selectedAdCount = state.selectedAds.length;
    const totalRecipients = state.smsUsers.length + state.emailUsers.length;
    
    let html = `
        <div class="result-summary">
            <h3>✅ Campaign Completed!</h3>
            <div class="result-stats">
                <div class="stat-item">
                    <div class="stat-value">${selectedAdCount}</div>
                    <div class="stat-label">Ads Sent</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${totalRecipients}</div>
                    <div class="stat-label">Recipients</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${summary.successful_sms + summary.successful_email}</div>
                    <div class="stat-label">Delivered</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${summary.failed_sms + summary.failed_email}</div>
                    <div class="stat-label">Failed</div>
                </div>
            </div>
            <p style="text-align: center; color: #6c757d; margin-top: 15px;">
                ${selectedAdCount} ad${selectedAdCount !== 1 ? 's' : ''} sent to ${totalRecipients} recipient${totalRecipients !== 1 ? 's' : ''}
            </p>
        </div>
        
        <div class="result-card">
            <h4>📱 SMS Results</h4>
            <p>Recipients: ${state.smsUsers.length} | Delivered: ${summary.successful_sms} | Failed: ${summary.failed_sms}</p>
        </div>
        
        <div class="result-card">
            <h4>📧 Email Results</h4>
            <p>Recipients: ${state.emailUsers.length} | Delivered: ${summary.successful_email} | Failed: ${summary.failed_email}</p>
        </div>
    `;
    
    // Show error messages if any
    if (errorMessages.length > 0) {
        html += `
            <div class="result-card result-error">
                <h4>⚠️ Error Details</h4>
                <ul style="list-style-type: none; padding-left: 0;">
                    ${errorMessages.map(msg => `<li style="margin: 10px 0; padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;">${escapeHtml(msg)}</li>`).join('')}
                </ul>
                <p style="margin-top: 15px; color: #856404;">
                    <strong>Common Issues:</strong><br>
                    • Check if Twilio/SendGrid credentials are set correctly in .env file<br>
                    • Verify phone numbers are in E.164 format (+1234567890)<br>
                    • Check if email addresses are valid<br>
                    • Ensure API keys have proper permissions
                </p>
            </div>
        `;
    }
    
    resultsContainer.innerHTML = html;
}

// Start over
function startOver() {
    state = {
        generatedAds: [],
        smsUsers: [],
        emailUsers: [],
        competitorData: null,
        currentStep: 1
    };
    
    document.getElementById('competitorForm').reset();
    document.getElementById('smsName').value = '';
    document.getElementById('smsPhone').value = '';
    document.getElementById('emailName').value = '';
    document.getElementById('emailAddress').value = '';
    
    updateSMSUsersList();
    updateEmailUsersList();
    updateUserSummary();
    validateForm();
    
    showStep(1);
    
    const continueToUsers = document.getElementById('continueToUsers');
    if (continueToUsers) continueToUsers.style.display = 'none';
    
    const resultsNav = document.getElementById('resultsNavigation');
    if (resultsNav) resultsNav.style.display = 'none';
    
    const summaryContainer = document.getElementById('summaryContainer');
    if (summaryContainer) summaryContainer.style.display = 'none';
    
    const sendingResults = document.getElementById('sendingResults');
    if (sendingResults) sendingResults.innerHTML = '';
}

// Enter key handlers
document.getElementById('smsPhone')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        addSMSUser();
    }
});

document.getElementById('emailAddress')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        addEmailUser();
    }
});

// Parse competitor URL
async function parseCompetitorURL() {
    const urlInput = document.getElementById('competitor_url');
    const nameInput = document.getElementById('competitor_name');
    
    // Show URL input if hidden
    if (urlInput && urlInput.style.display === 'none') {
        urlInput.style.display = 'block';
        urlInput.focus();
        return;
    }
    
    const url = urlInput ? urlInput.value.trim() : '';
    if (!url) {
        showNotification('Please enter a URL', 'error');
        return;
    }
    
    try {
        showNotification('Parsing URL...', 'info');
        const response = await fetch('/api/parse-competitor-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        
        const result = await response.json();
        
        if (result.success) {
            if (result.competitor_name && nameInput && !nameInput.value) {
                nameInput.value = result.competitor_name;
                showNotification(`Extracted: ${result.competitor_name}`, 'success');
            }
            if (urlInput) {
                urlInput.style.display = 'none';
                urlInput.value = '';
            }
            validateForm();
        } else {
            showNotification(`Error: ${result.error}`, 'error');
        }
    } catch (error) {
        showNotification(`Error parsing URL: ${error.message}`, 'error');
    }
}

// Save ad as template
function saveAdAsTemplate(adIndex) {
    const ad = state.generatedAds[adIndex];
    if (!ad) return;
    
    const templateName = prompt('Enter a name for this template:');
    if (!templateName) return;
    
    // Save to localStorage (in production, use backend API)
    const templates = JSON.parse(localStorage.getItem('ad_templates') || '[]');
    templates.push({
        id: Date.now(),
        name: templateName,
        ad: ad,
        created_at: new Date().toISOString()
    });
    localStorage.setItem('ad_templates', JSON.stringify(templates));
    
    showNotification(`Template "${templateName}" saved!`, 'success');
}

// Show preview for email/SMS
function showAdPreview(adIndex, channel) {
    const ad = state.generatedAds[adIndex];
    if (!ad) return;
    
    let preview = '';
    let title = '';
    
    if (channel === 'sms') {
        title = 'SMS Preview';
        preview = `🎯 ${ad.headline}\n\n${ad.ad_text}\n\n${ad.cta}\n\nHashtags: ${ad.hashtags.join(', ')}`;
        preview = `<pre style="white-space: pre-wrap; font-family: monospace; padding: 15px; background: #f8f9fa; border-radius: 5px;">${escapeHtml(preview)}</pre>`;
    } else if (channel === 'email') {
        title = 'Email Preview';
        preview = `
            <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                <h2 style="color: #2c3e50;">🎯 New Ad Campaign</h2>
                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #e74c3c; margin-top: 0;">${escapeHtml(ad.headline)}</h3>
                    <p style="font-size: 16px;">${escapeHtml(ad.ad_text)}</p>
                    <p style="text-align: center; margin: 20px 0;">
                        <strong style="background: #3498db; color: white; padding: 12px 24px; border-radius: 5px; display: inline-block;">
                            ${escapeHtml(ad.cta)}
                        </strong>
                    </p>
                    <p style="color: #7f8c8d; font-size: 14px;">
                        Hashtags: ${ad.hashtags.map(t => escapeHtml(t)).join(', ')}
                    </p>
                </div>
            </div>
        `;
    }
    
    // Show in modal
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); z-index: 10000; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(4px);';
    
    const closeModal = () => {
        modal.style.opacity = '0';
        setTimeout(() => modal.remove(), 300);
    };
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
    
    modal.innerHTML = `
        <div class="modal-content" style="background: white; padding: 0; border-radius: 16px; max-width: 700px; width: 90%; position: relative; box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-height: 90vh; overflow: hidden; display: flex; flex-direction: column;">
            <div style="padding: 20px 24px; border-bottom: 2px solid #e9ecef; display: flex; justify-content: space-between; align-items: center; background: #fff;">
                <h3 style="margin: 0; color: #ff6600; font-size: 1.3em; font-weight: bold;">${title}</h3>
                <button class="modal-close-btn" style="position: relative; top: 0; right: 0; background: #f8f9fa; border: 2px solid #dee2e6; border-radius: 50%; width: 32px; height: 32px; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; color: #6c757d; transition: all 0.2s; line-height: 1; padding: 0;">&times;</button>
            </div>
            <div style="padding: 24px; overflow-y: auto; flex: 1;">
                ${preview}
            </div>
        </div>
    `;
    
    // Add click handler to close button
    setTimeout(() => {
        const closeBtn = modal.querySelector('.modal-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeModal);
            closeBtn.addEventListener('mouseenter', () => {
                closeBtn.style.background = '#ff6600';
                closeBtn.style.borderColor = '#ff6600';
                closeBtn.style.color = 'white';
            });
            closeBtn.addEventListener('mouseleave', () => {
                closeBtn.style.background = '#f8f9fa';
                closeBtn.style.borderColor = '#dee2e6';
                closeBtn.style.color = '#6c757d';
            });
        }
    }, 10);
    
    document.body.appendChild(modal);
    
    // Animate in
    setTimeout(() => {
        modal.style.opacity = '1';
    }, 10);
}

// ── Single Sender Verification ───────────────────────────────────────────────

// Toggle the verification panel open / closed
function toggleSenderPanel() {
    const body   = document.getElementById('senderVerifyBody');
    const toggle = document.getElementById('senderPanelToggle');
    if (!body) return;
    const isOpen = body.style.display !== 'none';
    body.style.display   = isOpen ? 'none' : 'block';
    toggle.textContent   = isOpen ? '▼' : '▲';
}

// Show / hide advanced address fields
function toggleSenderAdvanced() {
    const adv    = document.getElementById('senderAdvanced');
    const btn    = document.getElementById('senderAdvancedToggle');
    if (!adv) return;
    const isOpen = adv.style.display !== 'none';
    adv.style.display = isOpen ? 'none' : 'block';
    btn.textContent   = isOpen
        ? '⚙️ Advanced options (address, reply-to)'
        : '⚙️ Hide advanced options';
}

// Reset badge when the email field changes
function onSenderEmailChange() {
    _setSenderBadge('unknown', 'Not checked');
    _hideSenderStatus();
    const recheck = document.getElementById('recheckSenderBtn');
    if (recheck) recheck.style.display = 'none';
}

// Check whether the entered email is already a verified sender
async function checkSenderStatus() {
    const email = (document.getElementById('senderEmail')?.value || '').trim();
    if (!email) {
        _showSenderStatus('Please enter an email address first.', 'error');
        return;
    }

    _setSenderBadge('checking', 'Checking…');
    _hideSenderStatus();

    try {
        const res  = await fetch(`/api/sendgrid/sender-status?email=${encodeURIComponent(email)}`);
        const data = await res.json();

        if (!data.success) {
            _setSenderBadge('unknown', 'Error');
            _showSenderStatus('Could not check status: ' + data.error, 'error');
            return;
        }

        if (!data.found) {
            _setSenderBadge('unverified', 'Not registered');
            _showSenderStatus(
                `${email} is not yet registered as a sender. Click "Send Verification Email" to begin.`,
                'warning'
            );
        } else if (data.verified) {
            _setSenderBadge('verified', 'Verified ✓');
            _showSenderStatus(
                `✅ ${email} is verified and ready to send emails.`,
                'success'
            );
        } else {
            _setSenderBadge('pending', 'Pending');
            _showSenderStatus(
                `⏳ Verification email was sent to ${email} but not yet confirmed. Check your inbox.`,
                'warning'
            );
            document.getElementById('recheckSenderBtn').style.display = 'inline-block';
        }
    } catch (err) {
        _setSenderBadge('unknown', 'Error');
        _showSenderStatus('Network error: ' + err.message, 'error');
    }
}

// Request SendGrid to send a verification email to the entered address
async function verifySender() {
    const email    = (document.getElementById('senderEmail')?.value || '').trim();
    const name     = (document.getElementById('senderName')?.value || '').trim();
    const address  = (document.getElementById('senderAddress')?.value || '').trim();
    const city     = (document.getElementById('senderCity')?.value || '').trim();
    const state    = (document.getElementById('senderState')?.value || '').trim();
    const zip      = (document.getElementById('senderZip')?.value || '').trim();
    const country  = (document.getElementById('senderCountry')?.value || '').trim();
    const replyTo  = (document.getElementById('senderReplyTo')?.value || '').trim();

    if (!email) {
        _showSenderStatus('Please enter an email address first.', 'error');
        return;
    }

    const btn = document.getElementById('verifySenderBtn');
    const btnText   = btn?.querySelector('.btn-text');
    const btnLoader = btn?.querySelector('.btn-loader');
    if (btnText)   btnText.style.display   = 'none';
    if (btnLoader) btnLoader.style.display = 'inline-block';
    if (btn)       btn.disabled            = true;

    _setSenderBadge('checking', 'Sending…');
    _hideSenderStatus();

    try {
        const res  = await fetch('/api/sendgrid/verify-sender', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email,
                name:     name || email,
                nickname: name || email,
                reply_to: replyTo || email,
                address:  address || '123 Main St',
                city:     city    || 'City',
                state:    state,
                zip:      zip,
                country:  country || 'US'
            })
        });
        const data = await res.json();

        if (data.success) {
            if (data.verified) {
                _setSenderBadge('verified', 'Verified ✓');
                _showSenderStatus('✅ ' + data.message, 'success');
            } else if (data.already_exists) {
                _setSenderBadge('pending', 'Pending');
                _showSenderStatus('⏳ ' + data.message, 'warning');
                document.getElementById('recheckSenderBtn').style.display = 'inline-block';
            } else {
                _setSenderBadge('pending', 'Email sent');
                _showSenderStatus('✉️ ' + data.message, 'success');
                document.getElementById('recheckSenderBtn').style.display = 'inline-block';
            }
        } else {
            _setSenderBadge('unverified', 'Failed');
            _showSenderStatus('❌ ' + (data.error || 'Verification request failed.'), 'error');
        }
    } catch (err) {
        _setSenderBadge('unknown', 'Error');
        _showSenderStatus('Network error: ' + err.message, 'error');
    } finally {
        if (btnText)   btnText.style.display   = 'inline-block';
        if (btnLoader) btnLoader.style.display  = 'none';
        if (btn)       btn.disabled             = false;
    }
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _setSenderBadge(state, text) {
    const badge = document.getElementById('senderVerifyBadge');
    if (!badge) return;
    badge.textContent = text;
    badge.className = 'sender-badge sender-badge-' + state;
}

function _showSenderStatus(msg, type) {
    const el = document.getElementById('senderStatusMsg');
    if (!el) return;
    el.textContent  = msg;
    el.className    = 'sender-status-msg sender-status-' + type;
    el.style.display = 'block';
}

function _hideSenderStatus() {
    const el = document.getElementById('senderStatusMsg');
    if (el) el.style.display = 'none';
}

// ─────────────────────────────────────────────────────────────────────────────

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupRealTimeValidation();
    validateForm();
    updateSMSUsersList();
    updateEmailUsersList();
    updateUserSummary();
    updateNavigationButtons();
    
    // Handle URL input enter key
    const urlInput = document.getElementById('competitor_url');
    if (urlInput) {
        urlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                parseCompetitorURL();
            }
        });
    }
});
