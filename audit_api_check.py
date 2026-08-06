import frappe
from hesab_app.api import onboarding

onboarding_funcs = [n for n in dir(onboarding) if callable(getattr(onboarding, n)) and not n.startswith("_")]
print("=== CORRECTED API ENDPOINT LISTING (v16 whitelist check) ===")
for fname in sorted(onboarding_funcs):
    fn = getattr(onboarding, fname)
    in_whitelist = fn in frappe.whitelisted
    is_guest = fn in frappe.guest_methods if in_whitelist else False
    print(f"  {fname}: whitelisted={in_whitelist}, allow_guest={is_guest}")
