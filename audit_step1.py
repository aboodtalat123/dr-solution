import frappe; doctype='Hesab Business Settings'; meta=frappe.get_meta(doctype)
print('=== 1. DOCTYPE PERMISSION RULES ===')
if meta:
    print('DocType exists:', doctype); print('Permissions:')
    for p in frappe.get_doc('DocType', doctype).permissions:
        print(f'  Role: {p.role}, Level: {p.permlevel}, Read: {p.read}, Write: {p.write}, Create: {p.create}, Delete: {p.delete}')
else:
    print('DocType NOT FOUND')
