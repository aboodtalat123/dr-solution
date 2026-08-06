import frappe
import sys
import os

frappe.init(site="hesab.localhost", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()

print("=== 1. DOCTYPE PERMISSION RULES ===")
doctype = "Hesab Business Settings"
meta = frappe.get_meta(doctype)
if meta:
    print("DocType exists:", doctype)
    print("Permissions:")
    for p in frappe.get_doc("DocType", doctype).permissions:
        print(f"  Role: {p.role}, Level: {p.permlevel}, Read: {p.read}, Write: {p.write}, Create: {p.create}, Delete: {p.delete}")
else:
    print("DocType NOT FOUND")

print()
print("=== 2. ROLE EXISTENCE ===")
for r in ["Hesab User", "Hesab Admin"]:
    role = frappe.db.exists("Role", r)
    print(f'Role "{r}": {"EXISTS" if role else "MISSING"}')

print()
print("=== 3. GUEST REJECTION TEST ===")
frappe.set_user("Guest")
try:
    from hesab_app.api.onboarding import get_onboarding_status
    result = get_onboarding_status()
    print(f"GUEST ACCESS RESULT: {result}")
    print("WARNING: Guest user was able to access!")
except Exception as e:
    print(f"Guest correctly rejected: {type(e).__name__}: {e}")

print()
print("=== 4. NON-HESAB USER REJECTION TEST ===")
frappe.set_user("Administrator")
if not frappe.db.exists("Role", "Blogger"):
    role = frappe.get_doc({"doctype": "Role", "role_name": "Blogger"})
    role.insert(ignore_permissions=True)
    print("Created temporary 'Blogger' role")
user = frappe.get_doc({
    "doctype": "User",
    "email": "test_norole@example.com",
    "first_name": "Test",
    "send_welcome_email": False,
    "roles": [{"role": "Blogger"}]
})
user.insert(ignore_permissions=True, ignore_mandatory=True)
frappe.set_user("test_norole@example.com")
try:
    from hesab_app.api.onboarding import _require_save_role
    _require_save_role()
    print("WARNING: Non-Hesab user passed role check!")
except Exception as e:
    print(f"Non-Hesab user correctly rejected: {type(e).__name__}: {e}")

print()
print("=== 5. API ENDPOINT LISTING ===")
from hesab_app import api
onboarding_funcs = [n for n in dir(api.onboarding) if callable(getattr(api.onboarding, n)) and not n.startswith("_")]
for fname in sorted(onboarding_funcs):
    fn = getattr(api.onboarding, fname)
    if hasattr(fn, "is_whitelisted"):
        allow_guest = getattr(fn, "_allow_guest", False)
        print(f"  {fname}: whitelisted, allow_guest={allow_guest}")
    else:
        print(f"  {fname}: NOT whitelisted")

print()
print("=== CLEANUP ===")
frappe.set_user("Administrator")
if frappe.db.exists("User", "test_norole@example.com"):
    frappe.delete_doc("User", "test_norole@example.com", ignore_permissions=True, force=True)
    print("Cleaned up test user")
if frappe.db.exists("Role", "Blogger"):
    frappe.delete_doc("Role", "Blogger", ignore_permissions=True, force=True)
    print("Cleaned up Blogger role")
frappe.db.commit()

print("Done")
frappe.destroy()
