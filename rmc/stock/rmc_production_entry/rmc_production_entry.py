import frappe
import json
from frappe import _
from frappe.model.document import Document
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.accounts.utils import get_account_currency, get_company_default
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from erpnext.stock.doctype.rmc_production_entry.utils import get_default_cwip_account, get_mixing_expense_account
from frappe.utils import flt, getdate, now, time_diff_in_hours, get_datetime

class RMCProductionEntry(Document):
    def validate(self):
        self.validate_materials()
        self.validate_accounts()
        self.get_mixing_rate()
        self.calculate_costs()
        self.calculate_variances()

    def validate_accounts(self):
        """Ensure required accounts exist"""
        if self.total_mixing_cost:
            # Check accounts before submission
            cwip_account = get_default_cwip_account(self.company)
            mixing_expense_account = get_mixing_expense_account(self.company)
            cost_center = get_company_default(self.company, "cost_center")
            
            if not cwip_account or not mixing_expense_account:
                frappe.throw(_("Required accounts not set up. Please run account setup first."))
            if not cost_center:
                frappe.throw(_("Default cost center not set for company {0}").format(self.company))

    def validate_materials(self):
        """Ensure all required materials are entered with valid quantities"""
        if not self.raw_materials:
            frappe.throw(_("Raw materials cannot be empty"))
        
        for material in self.raw_materials:
            if material.qty <= 0:
                frappe.throw(_("Quantity must be greater than zero for {0}").format(material.item_name))

    @frappe.whitelist()
    def get_mixing_rate(self):
        """Get applicable mixing rate for the RMC grade"""
        self.mixing_rate = frappe.get_attr('erpnext.stock.doctype.rmc_grade_rate.rmc_grade_rate.RMCGradeRate').get_rate(
            self.rmc_grade,
            self.production_date,
            self.source_warehouse
        )
        return self.mixing_rate

    @frappe.whitelist()
    def get_bom_materials(self):
        """Fetch raw materials from BOM and populate estimated quantities"""
        if not self.bom:
            frappe.throw(_("Please select a BOM first"))
        
        bom = frappe.get_doc("BOM", self.bom)
        
        # Clear existing raw materials
        self.raw_materials = []
        
        for item in bom.items:
            # Calculate quantity based on production quantity and BOM quantity
            estimated_qty = item.qty * (self.quantity / bom.quantity)
            
            self.append("raw_materials", {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "description": item.description,
                "estimated_qty": estimated_qty,
                "qty": estimated_qty,  # Default actual to estimated
                "variance": 0,
                "variance_percent": 0,
                "uom": item.stock_uom,
                "rate": item.rate,
                "amount": item.rate * estimated_qty,                
                "conversion_factor": item.conversion_factor
            })
        
        self.calculate_costs()
        return self.raw_materials

    def on_submit(self):
        self.workflow_state = "Produced"
        self.status_changed_at = now()
        self.db_set('workflow_state', 'Produced', update_modified=False)
        self.db_set('status_changed_at', self.status_changed_at)
        self.create_stock_entries()

    @frappe.whitelist()
    def update_status(self, status=None):
        """Update status and create necessary transactions"""
        if not status:
            return

        if self.docstatus != 1:
            frappe.throw(_("Document must be submitted before updating status"))

        if status not in ["Produced", "In-Transit", "Delivered"]:
            frappe.throw(_("Invalid status"))

        # Validate status transition
        valid_transitions = {
            "Produced": ["In-Transit"],
            "In-Transit": ["Delivered"]
        }

        if self.workflow_state not in valid_transitions or status not in valid_transitions[self.workflow_state]:
            frappe.throw(_("Cannot change status from {0} to {1}").format(self.workflow_state, status))

        old_status = self.workflow_state
        status_changed_at = now()
        
        # Update workflow state
        self.db_set('workflow_state', status, update_modified=False)
        self.db_set('status_changed_at', status_changed_at)
        self.notify_update()
        self.reload()
        
        # Create appropriate stock entries based on transition
        try:
            if old_status == "Produced" and status == "In-Transit":
                self.create_transit_entry()
                frappe.msgprint(_("Created transit stock entry"))
            
            elif old_status == "In-Transit" and status == "Delivered":
                self.create_delivery_entry()
                frappe.msgprint(_("Created delivery stock entry"))

            frappe.db.commit()
            return True
        
        except Exception as e:
            frappe.db.rollback()
            frappe.throw(_("Error creating stock entries: {0}").format(str(e)))

    def get_status_info(self):
        """Get status age information"""
        if not self.status_changed_at:
            return None

        hours = time_diff_in_hours(now(), get_datetime(self.status_changed_at))
        
        alert_hours = {
            "Produced": 2,  # Alert after 2 hours
            "In-Transit": 4  # Alert after 4 hours
        }
        
        if self.workflow_state in alert_hours and hours > alert_hours[self.workflow_state]:
            return {
                "hours": hours,
                "alert": True,
                "message": _("This entry has been in {0} state for {1} hours").format(
                    self.workflow_state, 
                    frappe.utils.rounded(hours, 1)
                )
            }
            
        return {
            "hours": hours,
            "alert": False,
            "message": _("Time in current state: {0} hours").format(
                frappe.utils.rounded(hours, 1)
            )
        }
        
    def calculate_costs(self):
        """Calculate total and per unit costs including mixing charges"""
        self.total_raw_material_cost = sum(item.amount for item in self.raw_materials)
        self.total_mixing_cost = self.mixing_rate * self.quantity if self.mixing_rate else 0
        self.total_cost = (
            self.total_raw_material_cost + 
            (self.production_cost or 0) + 
            self.total_mixing_cost
        )
        self.per_unit_cost = self.total_cost / self.quantity if self.quantity else 0

    def calculate_variances(self):
        """Calculate variance between estimated and actual quantities"""
        for material in self.raw_materials:
            material.variance = material.qty - material.estimated_qty
            if material.estimated_qty:
                material.variance_percent = (material.variance / material.estimated_qty) * 100
            else:
                material.variance_percent = 0

    def create_stock_entries(self):
        """Create stock entries for material consumption and RMC production"""
        cost_center = get_company_default(self.company, "cost_center")
        posting_date = getdate(self.production_date)
        
        # Material Consumption Entry
        consumption_entry = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Issue",
            "purpose": "Material Issue",
            "company": self.company,
            "posting_date": posting_date,
            "posting_time": self.posting_time,
            "from_warehouse": self.source_warehouse,
            "rmc_production_entry": self.name
        })
        
        for item in self.raw_materials:
            item_stock_uom = frappe.db.get_value("Item", item.item_code, "stock_uom")
            consumption_entry.append("items", {
                "item_code": item.item_code,
                "qty": item.qty,
                "uom": item.uom,
                "stock_uom": item_stock_uom,
                "conversion_factor": 1.0,  # Using 1.0 as default since we're using same UOM
                "s_warehouse": self.source_warehouse,
                "cost_center": cost_center
            })
        
        consumption_entry.save()
        consumption_entry.submit()
        
        # RMC Production Entry
        production_entry = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Receipt",
            "purpose": "Material Receipt",
            "company": self.company,
            "posting_date": posting_date,
            "posting_time": self.posting_time,
            "to_warehouse": self.source_warehouse,
            "rmc_production_entry": self.name
        })
        
        production_entry.append("items", {
            "item_code": self.rmc_grade,
            "qty": self.quantity,            
            "stock_uom": frappe.db.get_value("Item", self.rmc_grade, "stock_uom"),
            "conversion_factor": 1.0,
            "t_warehouse": self.source_warehouse,
            "cost_center": cost_center,
            "basic_rate": self.per_unit_cost
        })
        
        production_entry.save()
        production_entry.submit()

        # Create GL Entry for mixing charges if applicable
        if self.total_mixing_cost:
            self.create_mixing_charges_entry()

    def create_mixing_charges_entry(self):
        """Create GL Entry for mixing charges"""
        if not self.total_mixing_cost:
            return
            
        # Get accounts
        cwip_account = get_default_cwip_account(self.company)
        mixing_expense_account = get_mixing_expense_account(self.company)
        cost_center = get_company_default(self.company, "cost_center")
        
        gl_entries = []
        precision = frappe.get_precision("GL Entry", "debit")
        
        gl_entries.append(
            self.get_gl_dict({
                "account": cwip_account,
                "against": mixing_expense_account,
                "debit": flt(self.total_mixing_cost, precision),
                "debit_in_account_currency": flt(self.total_mixing_cost, precision),
                "cost_center": cost_center,
                "remarks": f"Mixing charges for {self.name}"
            })
        )

        gl_entries.append(
            self.get_gl_dict({
                "account": mixing_expense_account,
                "against": cwip_account,
                "credit": flt(self.total_mixing_cost, precision),
                "credit_in_account_currency": flt(self.total_mixing_cost, precision),
                "cost_center": cost_center,
                "remarks": f"Mixing charges for {self.name}"
            })
        )

        if gl_entries:
            try:
                make_gl_entries(gl_entries, merge_entries=False)
            except Exception as e:
                frappe.throw(_("GL Entry creation failed: {0}").format(str(e)))

    def get_gl_dict(self, args):
        """Helper function to get GL Dict with common fields"""
        account_currency = get_account_currency(args.get('account'))
        
        gl_dict = frappe._dict({
            'company': self.company,
            'posting_date': getdate(self.production_date),
            'voucher_type': self.doctype,
            'voucher_no': self.name,
            'against_voucher_type': None,
            'against_voucher': None,
            'account': args.get('account'),
            'party_type': None,
            'party': None,
            'cost_center': args.get('cost_center'),
            'against': args.get('against'),
            'credit': args.get('credit', 0),
            'debit': args.get('debit', 0),
            'account_currency': account_currency,
            'debit_in_account_currency': args.get('debit_in_account_currency', args.get('debit', 0)),
            'credit_in_account_currency': args.get('credit_in_account_currency', args.get('credit', 0)),
            'against_voucher_type': None,
            'against_voucher': None,
            'remarks': args.get('remarks', ''),
            'project': None,
            'is_opening': 'No',
            'is_advance': 'No'
        })
        
        gl_dict.update(args)
        return gl_dict

    def create_transit_entry(self):
        """Create stock entry for transit movement"""
        cost_center = get_company_default(self.company, "cost_center")
        
        posting_date = getdate(self.production_date)
        
        transit_entry = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Transfer",
            "purpose": "Material Transfer",
            "company": self.company,
            "posting_date": posting_date,
            "posting_time": self.posting_time,
            "rmc_production_entry": self.name
        })
        
        transit_entry.append("items", {
            "item_code": self.rmc_grade,
            "qty": self.quantity,            
            "stock_uom": frappe.db.get_value("Item", self.rmc_grade, "stock_uom"),
            "conversion_factor": 1.0,
            "s_warehouse": self.source_warehouse,
            "t_warehouse": "RMC Transit - MKB",
            "cost_center": cost_center,
            "basic_rate": self.per_unit_cost
        })
        
        transit_entry.save()
        transit_entry.submit()

    def create_delivery_entry(self):
        """Create stock entry for delivery to site"""
        cost_center = get_company_default(self.company, "cost_center")
        
        posting_date = getdate(self.production_date)
        
        delivery_entry = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Transfer",
            "purpose": "Material Transfer",
            "company": self.company,
            "posting_date": posting_date,
            "posting_time": self.posting_time,
            "rmc_production_entry": self.name
        })
        
        delivery_entry.append("items", {
            "item_code": self.rmc_grade,
            "qty": self.quantity,            
            "stock_uom": frappe.db.get_value("Item", self.rmc_grade, "stock_uom"),
            "conversion_factor": 1.0,
            "s_warehouse": "RMC Transit - MKB",
            "t_warehouse": self.destination_warehouse,
            "cost_center": cost_center,
            "basic_rate": self.per_unit_cost
        })
        
        delivery_entry.save()
        delivery_entry.submit()

@frappe.whitelist()
def update_status(docs, status):
    """Server-side handler for bulk status updates"""
    if not docs:
        return
        
    if isinstance(docs, str):
        docs = json.loads(docs)
        
    success = []
    failed = []
    
    for d in docs:
        try:
            doc = frappe.get_doc('RMC Production Entry', d.get('name'))
            if doc.update_status(status):
                success.append(d.get('name'))
            else:
                failed.append(d.get('name'))
        except Exception as e:
            failed.append(d.get('name'))
            frappe.log_error(f"Failed to update status for {d.get('name')}: {str(e)}")
            
    if failed:
        frappe.msgprint(
            _("Status update failed for the following: {0}").format(
                "<br>".join(failed)
            ),
            title=_("Status Update Failed"),
            indicator="red"
        )
    
    if success:
        frappe.msgprint(
            _("Status updated successfully for {0} documents").format(len(success)),
            indicator="green"
        )
        
    return {"success": success, "failed": failed}

@frappe.whitelist()
def update_single_status(name, status):
    """Update status for a single RMC Production Entry"""
    doc = frappe.get_doc('RMC Production Entry', name)
    return doc.update_status(status)
