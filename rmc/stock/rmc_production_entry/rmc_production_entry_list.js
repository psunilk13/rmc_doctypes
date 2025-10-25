frappe.listview_settings['RMC Production Entry'] = {
    add_fields: ["workflow_state", "docstatus", "status_changed_at"],
    
    get_indicator: function(doc) {
        const hours = doc.status_changed_at ? 
            frappe.datetime.get_hour_diff(frappe.datetime.now_datetime(), doc.status_changed_at) : 
            0;

        const alert_hours = {
            "Produced": 2,
            "In-Transit": 4
        };

        const status = doc.workflow_state;
        let color = "gray";
        
        if (doc.docstatus === 0) {
            return [__("Draft"), "gray", "workflow_state,=,Draft"];
        }
        
        // Determine color based on status and hours
        if (status === "Produced") {
            color = hours > alert_hours[status] ? "red" : "blue";
        } else if (status === "In-Transit") {
            color = hours > alert_hours[status] ? "red" : "orange";
        } else if (status === "Delivered") {
            color = "green";
        }

        const label = hours ? `${__(status)} (${Math.round(hours)}h)` : __(status);
        return [label, color, `workflow_state,=,${status}`];
    },

    onload(listview) {
        // Add refresh handler
        listview.page.wrapper.on('page-change', () => {
            listview.refresh();
        });

        // Add refresh every 5 minutes for status age
        setInterval(() => {
            if (listview.page.wrapper.is(':visible')) {
                listview.refresh();
            }
        }, 300000); // 5 minutes

        // Add bulk update button
        listview.page.add_inner_button(__("Set Status"), () => {
            if (!listview.get_checked_items().length) {
                frappe.msgprint(__("Please select at least one document"));
                return;
            }

            // Check if all selected items are submitted
            const hasUnsubmitted = listview.get_checked_items().some(d => d.docstatus !== 1);
            if (hasUnsubmitted) {
                frappe.msgprint(__("Please select only submitted documents"));
                return;
            }

            // Group selected items by current status
            const items = listview.get_checked_items();
            const statusGroups = {};
            items.forEach(item => {
                if (!statusGroups[item.workflow_state]) {
                    statusGroups[item.workflow_state] = [];
                }
                statusGroups[item.workflow_state].push(item.name);
            });

            // Validate if all selected items have same status
            if (Object.keys(statusGroups).length > 1) {
                frappe.msgprint(__("Please select documents with same status"));
                return;
            }

            const currentStatus = Object.keys(statusGroups)[0];
            const validNextStates = {
                "Produced": ["In-Transit"],
                "In-Transit": ["Delivered"]
            };

            const dialog = new frappe.ui.Dialog({
                title: __("Update Status"),
                fields: [
                    {
                        fieldname: "status",
                        label: __("Status"),
                        fieldtype: "Select",
                        options: validNextStates[currentStatus] ? validNextStates[currentStatus].join("\n") : "",
                        reqd: 1
                    }
                ],
                primary_action_label: __("Update"),
                primary_action(values) {
                    frappe.call({
                        method: 'erpnext.stock.doctype.rmc_production_entry.rmc_production_entry.update_status',
                        args: {
                            docs: JSON.stringify(listview.get_checked_items()),
                            status: values.status
                        },
                        freeze: true,
                        freeze_message: __("Updating Status..."),
                        callback: (r) => {
                            if (!r.exc) {
                                if (r.message) {
                                    if (r.message.failed && r.message.failed.length) {
                                        frappe.msgprint({
                                            title: __("Status Update Partially Failed"),
                                            message: __("Failed to update status for: {0}", [r.message.failed.join("<br>")]),
                                            indicator: "orange"
                                        });
                                    } else {
                                        frappe.show_alert({
                                            message: __("Status updated successfully"),
                                            indicator: "green"
                                        });
                                    }
                                }
                                dialog.hide();
                                listview.refresh();
                            }
                        }
                    });
                }
            });

            // Show only valid next states
            if (!validNextStates[currentStatus]) {
                frappe.msgprint(__("No further status updates allowed for {0}", [currentStatus]));
                return;
            }

            dialog.show();
        });
    }
};
