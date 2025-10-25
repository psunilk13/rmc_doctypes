import frappe
from frappe import _

def setup_accounts(company):
    """Setup required accounts for RMC Production Entry"""
    if not company:
        frappe.throw(_("Company is required"))
        
    abbr = frappe.get_value('Company', company, 'abbr')
    if not abbr:
        frappe.throw(_("Company abbreviation not found"))

    # Check parent accounts exist
    parent_accounts = [
        f"Application of Funds (Assets) - {abbr}",
        f"Direct Expenses - {abbr}"
    ]
    
    for parent in parent_accounts:
        if not frappe.db.exists("Account", parent):
            frappe.throw(_("Parent account {0} not found. Please set up standard accounts first.").format(parent))
    
    accounts_to_create = [
        {
            "account_name": "Capital Work in Progress",
            "parent_account": f"Application of Funds (Assets) - {abbr}",
            "account_type": "Capital Work in Progress",
            "is_group": 0,
            "root_type": "Asset"
        },
        {
            "account_name": "RMC Mixing Expenses",
            "parent_account": f"Direct Expenses - {abbr}",
            "account_type": "Direct Expenses",
            "is_group": 0,
            "root_type": "Expense"
        }
    ]
    
    created_accounts = []
    for acc in accounts_to_create:
        account_name = f"{acc['account_name']} - {abbr}"
        if not frappe.db.exists("Account", account_name):
            try:
                new_account = frappe.get_doc({
                    "doctype": "Account",
                    "account_name": acc["account_name"],
                    "parent_account": acc["parent_account"],
                    "account_type": acc["account_type"],
                    "root_type": acc["root_type"],
                    "company": company,
                    "is_group": acc["is_group"]
                })
                new_account.insert()
                created_accounts.append(account_name)
                
                if acc["account_name"] == "Capital Work in Progress":
                    frappe.db.set_value(
                        "Company", 
                        company, 
                        "capital_work_in_progress_account", 
                        account_name
                    )
            except Exception as e:
                frappe.log_error(f"Error creating account {account_name}: {str(e)}")
                frappe.throw(_("Error creating account {0}: {1}").format(account_name, str(e)))
    
    if created_accounts:
        frappe.msgprint(_("Created accounts: {0}").format(", ".join(created_accounts)))
    
    frappe.db.commit()

def get_default_cwip_account(company):
    """Get or create Capital Work in Progress account"""
    if not company:
        frappe.throw(_("Company is required"))
        
    abbr = frappe.get_value('Company', company, 'abbr')
    cwip_account = f"Capital Work in Progress - {abbr}"
    
    if not frappe.db.exists("Account", cwip_account):
        setup_accounts(company)
        
    if not frappe.db.exists("Account", cwip_account):
        frappe.throw(_("Could not find or create Capital Work in Progress account"))
    
    return cwip_account

def get_mixing_expense_account(company):
    """Get or create RMC Mixing Expenses account"""
    if not company:
        frappe.throw(_("Company is required"))
        
    abbr = frappe.get_value('Company', company, 'abbr')
    mixing_account = f"RMC Mixing Expenses - {abbr}"
    
    if not frappe.db.exists("Account", mixing_account):
        setup_accounts(company)
        
    if not frappe.db.exists("Account", mixing_account):
        frappe.throw(_("Could not find or create RMC Mixing Expenses account"))
    
    return mixing_account
