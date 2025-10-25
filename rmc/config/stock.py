from frappe import _

def get_data():
    return [
        {
            "label": _("RMC Production"),
            "items": [
                {
                    "type": "doctype",
                    "name": "RMC Production Entry",
                    "label": _("RMC Production Entry"),
                    "description": _("Manage RMC production entries")
                },
                {
                    "type": "doctype",
                    "name": "RMC Grade Rate",
                    "label": _("RMC Grade Rate")
                },
                {
                    "type": "doctype",
                    "name": "RMC Raw Materials",
                    "label": _("RMC Raw Materials")
                }
            ]
        }
    ]
