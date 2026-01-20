# Custom Templates Implementation Plan

## Overview
Scalable solution for custom email and PDF templates supporting thousands of users with different branding and template requirements.

## Architecture: Hybrid 3-Tier Approach

### Tier 1: Branding Settings (Realtime Database)
**Path:** `HomeHive/PropertyManagement/Settings/{companyId}/branding`

**Data Structure:**
```json
{
  "companyName": "ACME Properties",
  "logoUrl": "https://storage.../logos/company123.png",
  "primaryColor": "#2563eb",
  "secondaryColor": "#1e40af",
  "accentColor": "#f59e0b",
  "footerText": "ACME Properties Ltd. | www.acme.com",
  "emailSignature": "Best regards,\nThe ACME Team",
  "phoneNumber": "+1234567890",
  "websiteUrl": "https://acme.com",
  "address": "123 Main St, City, Country"
}
```

**Advantages:**
- Fast access (no file downloads)
- Lightweight storage
- Easy to edit via admin UI
- Instant updates
- Low cost

**Use Case:** Simple branding customization (90% of users)

---

### Tier 2: Custom Templates (Firebase Storage)
**Path:** `Templates/{companyId}/{type}/{template_name}.html`

**Directory Structure:**
```
Templates/
  ├── defaults/                    # Backup of default templates
  │   ├── email/
  │   │   ├── receipt_email.html
  │   │   ├── invoice_email.html
  │   │   └── document_share_email.html
  │   └── pdf/
  │       ├── receipt_template.html
  │       └── invoice_template.html
  │
  ├── {companyId1}/
  │   ├── email/
  │   │   ├── receipt_email.html        # Custom receipt email
  │   │   ├── invoice_email.html        # Custom invoice email
  │   │   └── document_share_email.html # Custom document email
  │   └── pdf/
  │       ├── receipt_template.html     # Custom receipt PDF
  │       └── invoice_template.html     # Custom invoice PDF
  │
  ├── {companyId2}/
  │   └── ...
  │
  └── {companyId...}/                   # Thousands of companies
```

**Advantages:**
- Full HTML/CSS customization
- Manageable via frontend upload
- Version control possible
- No code deployment needed

**Use Case:** Advanced users needing full template control (10% of users)

---

### Tier 3: Default Templates (Cloud Functions Code)
**Location:** Current templates in `functions/templates/`

**Purpose:**
- Fallback when no custom template exists
- Base templates for new companies
- Reference templates for customization

---

## Implementation Details

### 1. Template Loader (Python)

**File:** `functions/services/template_loader.py`

```python
from functools import lru_cache
from jinja2 import Template
from firebase_admin import storage, db
import time
import logging

log = logging.getLogger(__name__)

# In-memory cache
template_cache = {}
CACHE_TTL = 3600  # 1 hour

@lru_cache(maxsize=1000)
def get_template(company_id: str, template_name: str, template_type: str = 'email'):
    """
    Load template with 3-tier fallback:
    1. Custom template from Firebase Storage
    2. Default template from code
    3. Inject branding settings

    Args:
        company_id: Company identifier
        template_name: Template filename (e.g., 'receipt_email.html')
        template_type: 'email' or 'pdf'

    Returns:
        Jinja2 Template object
    """
    cache_key = f"{company_id}_{template_type}_{template_name}"

    # Check cache
    if cache_key in template_cache:
        cached = template_cache[cache_key]
        if time.time() - cached['timestamp'] < CACHE_TTL:
            log.debug(f"Template cache hit: {cache_key}")
            return cached['template']

    template_content = None

    # Try to load custom template from Firebase Storage
    try:
        custom_path = f"Templates/{company_id}/{template_type}/{template_name}"
        bucket = storage.bucket()
        blob = bucket.blob(custom_path)

        if blob.exists():
            template_content = blob.download_as_text()
            log.info(f"Loaded custom template for {company_id}: {template_name}")
        else:
            log.debug(f"No custom template found at: {custom_path}")
    except Exception as e:
        log.warning(f"Error loading custom template for {company_id}: {e}")

    # Fallback to default template from code
    if not template_content:
        from utils.template_renderer import template_env
        try:
            default_template = template_env.get_template(template_name)
            template_content = default_template.render()
            log.debug(f"Using default template: {template_name}")
        except Exception as e:
            log.error(f"Error loading default template {template_name}: {e}")
            raise ValueError(f"Template not found: {template_name}")

    # Create Jinja2 template
    template = Template(template_content)

    # Cache the template
    template_cache[cache_key] = {
        'template': template,
        'timestamp': time.time()
    }

    return template


def get_branding_settings(company_id: str) -> dict:
    """
    Get company branding settings from Realtime Database

    Args:
        company_id: Company identifier

    Returns:
        Dictionary with branding settings
    """
    branding_path = f"HomeHive/PropertyManagement/Settings/{company_id}/branding"
    ref = db.reference(branding_path)
    branding = ref.get()

    # Return defaults if not found
    if not branding:
        log.info(f"No branding settings found for {company_id}, using defaults")
        return {
            'companyName': 'HomeHive',
            'primaryColor': '#2563eb',
            'secondaryColor': '#1e40af',
            'accentColor': '#f59e0b',
            'logoUrl': '',
            'footerText': 'Powered by HomeHive',
            'emailSignature': 'Best regards,\nThe Team'
        }

    return branding


def clear_template_cache(company_id: str = None, template_name: str = None):
    """
    Clear template cache for a specific company or template

    Args:
        company_id: If provided, clear all templates for this company
        template_name: If provided with company_id, clear specific template
    """
    if company_id and template_name:
        # Clear specific template
        for template_type in ['email', 'pdf']:
            cache_key = f"{company_id}_{template_type}_{template_name}"
            template_cache.pop(cache_key, None)
        log.info(f"Cleared cache for {company_id}/{template_name}")
    elif company_id:
        # Clear all templates for company
        keys_to_remove = [k for k in template_cache.keys() if k.startswith(f"{company_id}_")]
        for key in keys_to_remove:
            template_cache.pop(key, None)
        log.info(f"Cleared all cached templates for {company_id}")
    else:
        # Clear entire cache
        template_cache.clear()
        log.info("Cleared entire template cache")


def validate_template(template_content: str, required_vars: list) -> dict:
    """
    Validate template has required variables

    Args:
        template_content: Template HTML content
        required_vars: List of required variable names

    Returns:
        Dictionary with validation results
    """
    try:
        template = Template(template_content)
        # Basic syntax check by trying to render with dummy data
        dummy_context = {var: f"{{{{ {var} }}}}" for var in required_vars}
        template.render(**dummy_context)

        return {
            'valid': True,
            'message': 'Template is valid'
        }
    except Exception as e:
        return {
            'valid': False,
            'message': f'Template validation failed: {str(e)}'
        }
```

---

### 2. Updated Email Service

**File:** `functions/services/email_service.py`

```python
from services.template_loader import get_template, get_branding_settings

def send_email(recipient_email: str, subject: str, template_name: str,
               company_id: str, context: dict) -> bool:
    """
    Send email using custom or default template

    Args:
        recipient_email: Recipient email address
        subject: Email subject
        template_name: Template filename
        company_id: Company identifier
        context: Template variables

    Returns:
        True if email sent successfully
    """
    try:
        # Get branding settings
        branding = get_branding_settings(company_id)

        # Merge branding into context
        full_context = {
            **context,
            'branding': branding,
            'company_name': branding.get('companyName'),
            'primary_color': branding.get('primaryColor'),
            'secondary_color': branding.get('secondaryColor'),
            'accent_color': branding.get('accentColor'),
            'logo_url': branding.get('logoUrl'),
            'footer_text': branding.get('footerText'),
            'email_signature': branding.get('emailSignature'),
            'current_year': datetime.now().year
        }

        # Get template (custom or default)
        template = get_template(company_id, template_name, 'email')

        # Render with full context
        html_content = template.render(full_context)

        # Send email using existing email service
        # ... existing email sending code ...

        return True

    except Exception as e:
        log.error(f"Error sending email: {e}")
        return False
```

---

### 3. Updated PDF Service

**File:** `functions/services/receipt_service.py` and `functions/services/invoice_service.py`

```python
from services.template_loader import get_template, get_branding_settings

def generate_receipt_pdf(receipt_data: dict) -> bytes:
    """
    Generate receipt PDF using custom or default template
    """
    company_id = receipt_data.get('company_id')

    # Get branding settings
    branding = get_branding_settings(company_id)

    # Merge branding into context
    context = {
        **receipt_data,
        'branding': branding,
        'company_name': branding.get('companyName'),
        'logo_url': branding.get('logoUrl'),
        'primary_color': branding.get('primaryColor'),
        'footer_text': branding.get('footerText')
    }

    # Get template
    template = get_template(company_id, 'receipt_template.html', 'pdf')

    # Render HTML
    html_content = template.render(context)

    # Convert to PDF (existing code)
    # ...

    return pdf_bytes
```

---

## Frontend Implementation

### 1. Settings Service

**File:** `src/app/services/settings.service.ts`

```typescript
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { FirebaseService } from './firebase-manager/firebase.service';
import { UserService } from './user.service';

export interface BrandingSettings {
  companyName: string;
  logoUrl: string;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  footerText: string;
  emailSignature: string;
  phoneNumber?: string;
  websiteUrl?: string;
  address?: string;
}

@Injectable({
  providedIn: 'root'
})
export class SettingsService {
  private readonly basePath = 'HomeHive/PropertyManagement/Settings';
  private brandingPath: string;

  constructor(
    private firebaseService: FirebaseService<BrandingSettings>,
    private userService: UserService
  ) {
    const companyId = this.userService.getUserFromCache()?.companyId;
    this.brandingPath = `${this.basePath}/${companyId}/branding`;
  }

  getBrandingSettings(): Observable<BrandingSettings | undefined> {
    return this.firebaseService.readData(this.brandingPath);
  }

  updateBrandingSettings(settings: BrandingSettings): Observable<void> {
    return this.firebaseService.updateData(this.brandingPath, settings);
  }
}
```

### 2. Template Upload Service

**File:** `src/app/services/template.service.ts`

```typescript
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { FirebaseStorageService } from './firebase-manager/firesbase-storage.service';
import { UserService } from './user.service';

@Injectable({
  providedIn: 'root'
})
export class TemplateService {
  constructor(
    private storageService: FirebaseStorageService,
    private userService: UserService
  ) {}

  uploadTemplate(
    file: File,
    templateType: 'email' | 'pdf',
    templateName: string
  ): Observable<any> {
    const companyId = this.userService.getUserFromCache()?.companyId;
    const path = `Templates/${companyId}/${templateType}/${templateName}`;

    return this.storageService.uploadFile(file, path);
  }

  deleteTemplate(
    templateType: 'email' | 'pdf',
    templateName: string
  ): Observable<void> {
    const companyId = this.userService.getUserFromCache()?.companyId;
    const path = `Templates/${companyId}/${templateType}/${templateName}`;

    return this.storageService.deleteFile(path);
  }
}
```

---

## Performance & Scalability

### Caching Strategy
- **LRU Cache**: Maximum 1000 templates in memory
- **TTL**: 1 hour (configurable)
- **Cache Key Format**: `{companyId}_{templateType}_{templateName}`
- **Memory Usage**: ~50KB per template × 1000 = ~50MB (acceptable for Cloud Functions)

### Storage Costs (Estimated)
- **Per Template**: ~10-50KB
- **Per Company**: ~5 templates × 30KB = 150KB
- **1,000 Companies**: 150MB total
- **10,000 Companies**: 1.5GB total
- **Cost**: ~$0.026 per GB/month = Negligible

### Performance Benchmarks
- **Cold Start** (no cache): ~200-300ms to download template
- **Warm Start** (cached): ~1-5ms to retrieve from memory
- **Database Read** (branding): ~50ms

### Scaling Considerations
- Cloud Functions automatically scale horizontally
- Each instance has its own cache
- Cache warm-up happens naturally with traffic
- No coordination needed between instances

---

## Migration Path

### Phase 1: Branding Settings (Week 1-2)
**Goal:** Allow basic branding customization

**Tasks:**
1. Create SettingsService in frontend
2. Add branding settings UI in admin panel
3. Update email_service.py to use branding settings
4. Update PDF services to use branding settings
5. Test with default templates

**Impact:** Low risk, high value - covers 90% of customization needs

---

### Phase 2: Template Loader Infrastructure (Week 3-4)
**Goal:** Implement template loading system

**Tasks:**
1. Create template_loader.py service
2. Implement caching mechanism
3. Add template validation
4. Update email and PDF services to use template loader
5. Deploy with fallback to existing templates

**Impact:** Medium risk, enables full customization

---

### Phase 3: Template Upload UI (Week 5-6)
**Goal:** Allow users to upload custom templates

**Tasks:**
1. Create TemplateService in frontend
2. Build template manager component
3. Add template preview functionality
4. Implement template validation on frontend
5. Add template editor with syntax highlighting

**Impact:** Low risk, user-facing feature

---

### Phase 4: Advanced Features (Week 7-8)
**Goal:** Template versioning and management

**Tasks:**
1. Template version history
2. Template marketplace (optional)
3. Template migration tools
4. Analytics on template usage
5. A/B testing support

**Impact:** Low priority, nice-to-have features

---

## Template Variables Reference

### Common Variables (All Templates)
```python
{
    'branding': {
        'companyName': str,
        'logoUrl': str,
        'primaryColor': str,
        'secondaryColor': str,
        'accentColor': str,
        'footerText': str,
        'emailSignature': str
    },
    'current_year': int
}
```

### Receipt Email/PDF
```python
{
    'id_number': str,
    'payment_id': str,
    'tenant_name': str,
    'property_name': str,
    'date_paid': str,
    'next_payment_date': str,
    'amount_paid': float,
    'additional_info': [{'title': str, 'amount': float}]
}
```

### Invoice Email/PDF
```python
{
    'invoice_number': str,
    'tenant_info': {
        'name': str,
        'email': str,
        'idNumber': str
    },
    'due_rentals': [{
        'property_name': str,
        'amount': float,
        'due_date': str
    }],
    'total_amount': float,
    'due_date': str
}
```

### Document Share Email
```python
{
    'tenant_name': str,
    'document_title': str,
    'document_description': str,
    'document_type': str,
    'document_url': str
}
```

---

## Security Considerations

### Template Validation
- Sanitize template content before rendering
- Validate Jinja2 syntax
- Prevent code injection in templates
- Limit template size (max 500KB)

### Access Control
- Only company admins can upload templates
- Templates isolated per company (can't access other companies' templates)
- Storage security rules enforce company isolation

### Template Sandboxing
```python
from jinja2.sandbox import SandboxedEnvironment

# Use sandboxed environment for custom templates
sandbox_env = SandboxedEnvironment()
template = sandbox_env.from_string(template_content)
```

---

## Testing Strategy

### Unit Tests
```python
def test_template_loader_custom():
    # Test loading custom template
    template = get_template('company123', 'receipt_email.html', 'email')
    assert template is not None

def test_template_loader_fallback():
    # Test fallback to default
    template = get_template('nonexistent', 'receipt_email.html', 'email')
    assert template is not None

def test_branding_settings():
    # Test branding settings retrieval
    branding = get_branding_settings('company123')
    assert 'companyName' in branding
```

### Integration Tests
- Upload template via frontend
- Send email with custom template
- Generate PDF with custom template
- Verify caching behavior
- Test template validation

---

## Monitoring & Logging

### Metrics to Track
- Template cache hit rate
- Custom template usage percentage
- Template load time
- Storage usage per company
- Template validation failures

### Logging
```python
log.info(f"Template loaded: {company_id}/{template_name} (cache: {hit_type})")
log.warning(f"Template validation failed: {company_id}/{template_name}")
log.error(f"Template load error: {company_id}/{template_name} - {error}")
```

---

## Cost Estimation (10,000 companies)

### Storage
- Templates: 1.5GB × $0.026/GB/month = **$0.04/month**
- Logos: 1GB × $0.026/GB/month = **$0.03/month**

### Cloud Functions
- Memory: 512MB (includes cache)
- Executions: Covered by existing volume
- Additional cost: **Negligible**

### Realtime Database
- Branding settings: ~1KB per company × 10,000 = 10MB
- Cost: **Included in free tier**

**Total Additional Cost: ~$0.10/month for 10,000 companies**

---

## Rollback Plan

If issues arise, rollback is simple:
1. Set `USE_CUSTOM_TEMPLATES = False` environment variable
2. All functions fall back to default templates
3. No data loss (branding settings and custom templates remain)
4. Can re-enable when issues resolved

---

## Future Enhancements

### Template Marketplace
- Pre-built professional templates
- Community-contributed templates
- One-click template installation

### Visual Template Editor
- Drag-and-drop email builder
- Live preview
- Component library
- No-code customization

### Multi-language Support
- Template translations
- Language-specific branding
- Automatic language detection

### Advanced Analytics
- Email open rates by template
- PDF download tracking
- A/B testing templates
- Conversion optimization

---

## Conclusion

This hybrid 3-tier approach provides:
- ✅ **Scalability**: Supports millions of users with minimal cost
- ✅ **Performance**: Fast with intelligent caching
- ✅ **Flexibility**: From simple branding to full custom templates
- ✅ **Gradual Migration**: Implement in phases without disruption
- ✅ **Maintainability**: Clear separation of concerns
- ✅ **Cost-Effective**: ~$0.10/month for 10,000 companies

**Next Steps:**
1. Review and approve architecture
2. Begin Phase 1 implementation (Branding Settings)
3. Deploy incrementally with feature flags
4. Monitor performance and user adoption
5. Iterate based on feedback
