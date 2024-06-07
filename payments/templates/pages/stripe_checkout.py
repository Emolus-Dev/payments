# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import json

import frappe
from frappe import _
from frappe.utils import cint, fmt_money

from payments.payment_gateways.doctype.stripe_settings.stripe_settings import (
    get_gateway_controller,
)

no_cache = 1

expected_keys = (
    "amount",
    "title",
    "description",
    "reference_doctype",
    "reference_docname",
    "payer_name",
    "payer_email",
    "order_id",
    "currency",
)


def get_context(context):
    context.no_cache = 1

    # all these keys exist in form_dict
    if not (set(expected_keys) - set(list(frappe.form_dict))):
        for key in expected_keys:
            context[key] = frappe.form_dict[key]

        # Si el pago ya fue completado, se redirecciona a la url donde esta el voucher de pago
        validate_data_payment = verify_payment(
            context.reference_doctype, context.reference_docname
        )
        if validate_data_payment:
            frappe.local.response["type"] = "redirect"
            frappe.local.response["location"] = validate_data_payment.get("redirect_to")
            raise frappe.Redirect

        gateway_controller = get_gateway_controller(
            context.reference_doctype, context.reference_docname
        )

        context.publishable_key = get_api_key(
            context.reference_docname, gateway_controller
        )

        context.is_tokenization_enabled = frappe.db.get_value(
            "Stripe Settings", gateway_controller, "custom_enable_tokenization"
        )

        context.image = get_header_image(context.reference_docname, gateway_controller)

        context["amount"] = fmt_money(
            amount=context["amount"], currency=context["currency"]
        )

        if is_a_subscription(context.reference_doctype, context.reference_docname):
            payment_plan = frappe.db.get_value(
                context.reference_doctype, context.reference_docname, "payment_plan"
            )
            recurrence = frappe.db.get_value("Payment Plan", payment_plan, "recurrence")

            context["amount"] = context["amount"] + " " + _(recurrence)

    else:
        frappe.redirect_to_message(
            _("Some information is missing"),
            _(
                "Looks like someone sent you to an incomplete URL. Please ask them to look into it."
            ),
        )
        frappe.local.flags.redirect_location = frappe.local.response.location
        raise frappe.Redirect


def get_api_key(doc, gateway_controller):
    publishable_key = frappe.db.get_value(
        "Stripe Settings", gateway_controller, "publishable_key"
    )
    if cint(frappe.form_dict.get("use_sandbox")):
        publishable_key = frappe.conf.sandbox_publishable_key

    return publishable_key


def get_header_image(doc, gateway_controller):
    header_image = frappe.db.get_value(
        "Stripe Settings", gateway_controller, "header_img"
    )

    return header_image


@frappe.whitelist(allow_guest=True)
def make_payment(
    stripe_token_id,
    data,
    reference_doctype=None,
    reference_docname=None,
    save_payment_method="",
    result_stripe="{}",
):
    data = json.loads(data)

    data.update({"stripe_token_id": stripe_token_id})

    gateway_controller = get_gateway_controller(reference_doctype, reference_docname)
    frappe.log_error(title="gateway controller", message=gateway_controller)

    if is_a_subscription(reference_doctype, reference_docname):
        reference = frappe.get_doc(reference_doctype, reference_docname)
        data = reference.create_subscription("stripe", gateway_controller, data)

    else:
        # Se obtiene la configuracion de la pasarela de pago usada en la solicitud de pago
        data = frappe.get_doc("Stripe Settings", gateway_controller).create_request(
            data, save_payment_method, result_stripe
        )

    frappe.db.commit()
    return data


def is_a_subscription(reference_doctype, reference_docname):
    if not frappe.get_meta(reference_doctype).has_field("is_a_subscription"):
        return False
    return frappe.db.get_value(
        reference_doctype, reference_docname, "is_a_subscription"
    )


def verify_payment(reference_doctype, reference_docname):
    """
    Verifica si el pago ya fue completado, si lo fue se redirecciona a la url donde esta
    el voucher de pago.

    Args:
    reference_doctype: Payment Request dt
    reference_docname: Nombre de la solicitud de pago

    Returns:
    Dict: {"redirect_to": url, "status": "Completed"} o {}
    """
    try:
        payment_request_data = frappe.db.get_value(
            reference_doctype,
            filters={"name": reference_docname},
            fieldname=["name", "status", "pay_gate_visanet_token_ok_payment"],
            as_dict=True,
        )

        frappe.log_error(
            title="Verificando link de pago",
            message=f"url: {payment_request_data.pay_gate_visanet_token_ok_payment} - status: {payment_request_data.status}",
        )

        if (
            payment_request_data.status == "Paid"
            and payment_request_data.pay_gate_visanet_token_ok_payment != ""
        ):
            return {
                "redirect_to": payment_request_data.pay_gate_visanet_token_ok_payment,
                "status": "Completed",
            }

        return {}

    except Exception:
        frappe.log_error(
            title=f"Error verificar pago {reference_docname}",
            message=frappe.get_traceback(),
        )
        return {}
