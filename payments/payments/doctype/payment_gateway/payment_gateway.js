// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Gateway", {
  onload: function (frm) {
    frm.set_query("gateway_settings", () => {
      return {
        filters: {
          name: [
            "in",
            [
              "PowerTranz Settings",
              "ePayServer Settings",
              "Visanet Settings",
              "Stripe Settings",
            ],
          ],
        },
      };
    });
  },
  refresh: function (frm) {},
});
