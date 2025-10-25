import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

class RMCGradeRate(Document):
    def validate(self):
        self.validate_dates()
        self.validate_duplicate_rate()

    def validate_dates(self):
        """Ensure to_date is after from_date"""
        if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
            frappe.throw(_("To Date cannot be before From Date"))

    def validate_duplicate_rate(self):
        """Check for overlapping rate periods"""
        existing_rates = frappe.db.sql("""
            SELECT name, from_date, to_date
            FROM `tabRMC Grade Rate`
            WHERE
                rmc_grade = %s
                AND warehouse = %s
                AND name != %s
                AND disabled = 0
                AND ((from_date BETWEEN %s AND %s)
                    OR (to_date BETWEEN %s AND %s)
                    OR (from_date <= %s AND to_date >= %s))
        """, (
            self.rmc_grade,
            self.warehouse,
            self.name or "New RMC Grade Rate",
            self.from_date,
            self.to_date,
            self.from_date,
            self.to_date,
            self.from_date,
            self.to_date
        ), as_dict=1)

        if existing_rates:
            frappe.throw(_(
                "Rate already exists for {0} in Plant {1} for the selected period: {2} to {3}"
            ).format(
                self.rmc_grade,
                self.warehouse,
                existing_rates[0].from_date,
                existing_rates[0].to_date
            ))

    @staticmethod
    def get_rate(rmc_grade, date, warehouse):
        """Get applicable mixing rate for given parameters"""
        rate = frappe.db.get_value(
            "RMC Grade Rate",
            {
                "rmc_grade": rmc_grade,
                "warehouse": warehouse,
                "from_date": ("<=", date),
                "to_date": (">=", date),
                "disabled": 0
            },
            "rate"
        )

        if not rate:
            frappe.throw(_(
                "No mixing rate found for {0} in Plant {1} for date {2}"
            ).format(rmc_grade, warehouse, date))

        return rate
