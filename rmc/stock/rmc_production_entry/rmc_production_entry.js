// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('RMC Production Entry', {
    setup: function(frm) {
        frm.set_query("bom", function() {
            return {
                filters: {
                    "item": frm.doc.rmc_grade,
                    "is_active": 1,
                    "docstatus": 1
                }
            };
        });

        frm.set_query("rmc_grade", function() {
            return {
                filters: {
                    "item_group": "RMC"
                }
            };
        });
    },

    refresh: function(frm) {
        // Hide status field in new documents
        if (frm.is_new()) {
            frm.set_df_property('workflow_state', 'hidden', 1);
            frm.set_df_property('status_sb', 'hidden', 1);
        }

        frm.trigger('update_status_info');
        
        // Set up status info refresh timer
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== "Delivered") {
            if (!frm.status_update_timer) {
                frm.status_update_timer = setInterval(() => {
                    frm.trigger('update_status_info');
                }, 60000); // Update every minute
            }
        } else if (frm.status_update_timer) {
            clearInterval(frm.status_update_timer);
            frm.status_update_timer = null;
        }

        // Add status update buttons
        if (frm.doc.docstatus === 1) {
            let next_status = null;
            let btn_label = "";
            
            if (frm.doc.workflow_state === "Produced") {
                next_status = "In-Transit";
                btn_label = "Send to Transit";
            } else if (frm.doc.workflow_state === "In-Transit") {
                next_status = "Delivered";
                btn_label = "Mark as Delivered";
            }
            
            if (next_status) {
                frm.page.add_action_item(__(btn_label), () => {
                    frappe.confirm(
                        __('Are you sure you want to mark this as {0}?', [next_status]),
                        () => {
                            frappe.call({
                                method: 'erpnext.stock.doctype.rmc_production_entry.rmc_production_entry.update_single_status',
                                args: {
                                    name: frm.doc.name,
                                    status: next_status
                                },
                                freeze: true,
                                freeze_message: __("Updating Status..."),
                                callback: (r) => {
                                    if (!r.exc) {
                                        frm.reload_doc();
                                        frappe.show_alert({
                                            message: __('Status updated to {0}', [next_status]),
                                            indicator: 'green'
                                        });
                                    }
                                }
                            });
                        }
                    );
                });
            }
        }
    },

    update_status_info: function(frm) {
        if (!frm.doc.status_changed_at || !frm.doc.workflow_state || frm.doc.docstatus !== 1) {
            return;
        }

        const now = moment();
        const changed_at = moment(frm.doc.status_changed_at);
        const hours = moment.duration(now.diff(changed_at)).asHours();
        
        const alert_hours = {
            "Produced": 2,
            "In-Transit": 4
        };

        let html = __("Time in current state: {0} hours", [Math.round(hours * 10) / 10]);
        
        if (frm.doc.workflow_state in alert_hours && hours > alert_hours[frm.doc.workflow_state]) {
            html = `<div class="alert alert-warning">
                        <div>
                            <i class="fa fa-exclamation-triangle"></i>
                            ${__("Alert: This entry has been in {0} state for {1} hours", 
                                [frm.doc.workflow_state, Math.round(hours * 10) / 10])}
                        </div>
                    </div>`;
        }

        frm.set_value('time_in_current_state', html);
        frm.refresh_field('time_in_current_state');
    },

    rmc_grade: function(frm) {
        if (frm.doc.rmc_grade) {
            frm.set_value('bom', '');
            frm.get_field('bom').set_description('');
            frm.trigger('get_mixing_rate');
        }
    },

    quantity: function(frm) {
        frm.trigger('get_mixing_rate');
        if (frm.doc.bom) {
            // Fetch BOM materials again when quantity changes
            frm.trigger('bom');
        }
    },

    get_mixing_rate: function(frm) {
        if (frm.doc.rmc_grade && frm.doc.production_date && frm.doc.source_warehouse) {
            frm.call('get_mixing_rate')
                .then(() => frm.trigger('calculate_costs'));
        }
    },

    bom: function(frm) {
        if (frm.doc.bom) {
            frm.call('get_bom_materials')
                .then(() => frm.trigger('calculate_costs'));
        }
    },

    calculate_costs: function(frm) {
        let total_raw_material_cost = 0;
        
        (frm.doc.raw_materials || []).forEach(item => {
            total_raw_material_cost += flt(item.amount);
        });
        
        frm.set_value('total_raw_material_cost', total_raw_material_cost);
        
        const production_cost = flt(frm.doc.production_cost) || 0;
        const total_mixing_cost = flt(frm.doc.mixing_rate * frm.doc.quantity) || 0;
        
        frm.set_value('total_mixing_cost', total_mixing_cost);
        frm.set_value('total_cost', total_raw_material_cost + production_cost + total_mixing_cost);
        
        if (frm.doc.quantity) {
            frm.set_value('per_unit_cost', frm.doc.total_cost / frm.doc.quantity);
        }
    }
});

frappe.ui.form.on('RMC Raw Materials', {
    qty: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        row.amount = flt(row.qty) * flt(row.rate);
        
        // Calculate variance
        row.variance = flt(row.qty) - flt(row.estimated_qty);
        row.variance_percent = row.estimated_qty ? (row.variance / row.estimated_qty * 100) : 0;
        
        frm.refresh_field('raw_materials');
        frm.trigger('calculate_costs');
    },
    
    rate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        row.amount = flt(row.qty) * flt(row.rate);
        frm.refresh_field('raw_materials');
        frm.trigger('calculate_costs');
    }
});
