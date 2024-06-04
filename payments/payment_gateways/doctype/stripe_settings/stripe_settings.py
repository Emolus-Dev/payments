# Copyright (c) 2017, Frappe Technologies and contributors
# License: MIT. See LICENSE

import json
from typing import Any
from urllib.parse import urlencode

import frappe
import stripe
from frappe import _
from frappe.integrations.utils import create_request_log, make_get_request
from frappe.model.document import Document
from frappe.utils import call_hook_method, cint, flt, get_url, validate_email_address

from payments.utils import create_payment_gateway


class StripeSettings(Document):
    supported_currencies = [
        "AED",
        "ALL",
        "ANG",
        "ARS",
        "AUD",
        "AWG",
        "BBD",
        "BDT",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BWP",
        "BZD",
        "CAD",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HRK",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "ISK",
        "JMD",
        "JPY",
        "KES",
        "KHR",
        "KMF",
        "KRW",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "MAD",
        "MDL",
        "MNT",
        "MOP",
        "MRO",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RUB",
        "SAR",
        "SBD",
        "SCR",
        "SEK",
        "SGD",
        "SHP",
        "SLL",
        "SOS",
        "STD",
        "SVC",
        "SZL",
        "THB",
        "TOP",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "UYU",
        "UZS",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
    ]

    currency_wise_minimum_charge_amount = {
        "JPY": 50,
        "MXN": 10,
        "DKK": 2.50,
        "HKD": 4.00,
        "NOK": 3.00,
        "SEK": 3.00,
        "USD": 0.50,
        "AUD": 0.50,
        "BRL": 0.50,
        "CAD": 0.50,
        "CHF": 0.50,
        "EUR": 0.50,
        "GBP": 0.30,
        "NZD": 0.50,
        "SGD": 0.50,
    }

    def on_update(self):
        create_payment_gateway(
            "Stripe-" + self.gateway_name,
            settings="Stripe Settings",
            controller=self.gateway_name,
        )
        call_hook_method(
            "payment_gateway_enabled", gateway="Stripe-" + self.gateway_name
        )
        if not self.flags.ignore_mandatory:
            self.validate_stripe_credentails()

    def validate_stripe_credentails(self):
        if self.publishable_key and self.secret_key:
            header = {
                "Authorization": "Bearer {}".format(
                    self.get_password(fieldname="secret_key", raise_exception=False)
                )
            }
            try:
                make_get_request(
                    url="https://api.stripe.com/v1/charges", headers=header
                )
            except Exception:
                frappe.throw(_("Seems Publishable Key or Secret Key is wrong !!!"))

    def validate_transaction_currency(self, currency):
        if currency not in self.supported_currencies:
            frappe.throw(
                _(
                    "Please select another payment method. Stripe does not support transactions in currency '{0}'"
                ).format(currency)
            )

    def validate_minimum_transaction_amount(self, currency, amount):
        if currency in self.currency_wise_minimum_charge_amount:
            if flt(amount) < self.currency_wise_minimum_charge_amount.get(
                currency, 0.0
            ):
                frappe.throw(
                    _(
                        "For currency {0}, the minimum transaction amount should be {1}"
                    ).format(
                        currency,
                        self.currency_wise_minimum_charge_amount.get(currency, 0.0),
                    )
                )

    def get_payment_url(self, **kwargs):
        return get_url(f"./stripe_checkout?{urlencode(kwargs)}")

    def create_request(self, data, save_payment_method="", result_stripe={}):
        import stripe

        self.data = frappe._dict(data)
        stripe.api_key = self.get_password(
            fieldname="secret_key", raise_exception=False
        )

        stripe.default_http_client = stripe.http_client.RequestsClient()

        try:
            self.integration_request = create_request_log(
                self.data, service_name="Stripe"
            )
            self.save_payment_method = save_payment_method
            self.result_stripe = json.loads(result_stripe)
            return self.create_charge_on_stripe()

        except Exception:
            frappe.log_error(
                title="Error create request stripe", message=frappe.get_traceback()
            )
            return {
                "redirect_to": frappe.redirect_to_message(
                    _("Server Error"),
                    _(
                        "It seems that there is an issue with the server's stripe configuration. In case of failure, the amount will get refunded to your account."
                    ),
                ),
                "status": 401,
            }

    def create_charge_on_stripe(self) -> dict[str, Any]:
        try:
            # Si el usuario marco que desea guardar el metodo de pago
            if self.save_payment_method == "OK":
                status_response_stripe = self.attach_payment_method()

                if (
                    self.stripe_customer.id
                    and self.stripe_payment_method.id
                    and status_response_stripe
                ):
                    # Crear un cargo utilizando el cliente y el método de pago
                    self.charge = stripe.PaymentIntent.create(
                        customer=self.stripe_customer.id,
                        amount=cint(
                            flt(self.data.amount) * 100
                        ),  # El monto del cargo en centavos (por ejemplo, 2000 centavos = 20.00 USD)
                        currency=self.data.currency,
                        description=self.data.description,
                        payment_method=self.stripe_payment_method.id,  # Especificar el método de pago
                        receipt_email=self.data.payer_email,
                        confirm=True,
                    )

                    # Si el pago es OK
                    if self.charge.status == "succeeded":
                        self.integration_request.db_set(
                            "status", "Completed", update_modified=False
                        )

                        self.flags.status_changed_to = "Completed"

                    else:
                        frappe.log_error(
                            title=f"Stripe Payment not completed {self.data.reference_docname}",
                            message=self.charge.failure_message,
                        )

            # Si el usuario no marco que desear guardar el metodo de pago
            else:
                self.charge = stripe.Charge.create(
                    amount=cint(flt(self.data.amount) * 100),
                    currency=self.data.currency,
                    source=self.data.stripe_token_id,
                    description=self.data.description,
                    receipt_email=self.data.payer_email,
                )

                if self.charge.captured:
                    self.integration_request.db_set(
                        "status", "Completed", update_modified=False
                    )

                    self.flags.status_changed_to = "Completed"

                else:
                    frappe.log_error(
                        title=f"Stripe Payment not completed {self.data.reference_docname}",
                        message=self.charge.failure_message,
                    )

        except Exception:
            frappe.log_error(
                title=f"Error process payment Stripe {self.data.reference_docname}",
                message=frappe.get_traceback(),
            )

        self.save_stripe_response()

        return self.finalize_request()

    def finalize_request(self):
        redirect_to = self.data.get("redirect_to") or None
        redirect_message = self.data.get("redirect_message") or None
        status = self.integration_request.status

        if self.flags.status_changed_to == "Completed":
            if self.data.reference_doctype and self.data.reference_docname:
                custom_redirect_to = None

                try:
                    custom_redirect_to = frappe.get_doc(
                        self.data.reference_doctype, self.data.reference_docname
                    ).run_method("on_payment_authorized", self.flags.status_changed_to)

                except Exception:
                    frappe.log_error(
                        title="Error finalize request", message=frappe.get_traceback()
                    )

                if custom_redirect_to:
                    redirect_to = custom_redirect_to

                redirect_url = "payment-success?doctype={}&docname={}".format(
                    self.data.reference_doctype, self.data.reference_docname
                )

            if self.redirect_url:
                redirect_url = self.redirect_url
                redirect_to = None

        else:
            redirect_url = "payment-failed"

        if redirect_to and "?" in redirect_url:
            redirect_url += "&" + urlencode({"redirect_to": redirect_to})
        else:
            redirect_url += "?" + urlencode({"redirect_to": redirect_to})

        if redirect_message:
            redirect_url += "&" + urlencode({"redirect_message": redirect_message})

        return {"redirect_to": redirect_url, "status": status}

    def attach_payment_method(self) -> bool:
        """
        Adjunta el metodo de pago al cliente que este haciendo la transacción
        """
        try:
            self.stripe_customer = {}
            self.stripe_payment_method = {}

            if not validate_email_address(self.data.payer_email):
                return False

            pk_customer = frappe.db.get_value(
                "Payment Request", self.data.order_id, "party"
            )

            if not frappe.db.exists("Customer", pk_customer):
                return False

            frappe.set_user(self.data.payer_email)

            stripe.api_key = self.get_password(
                fieldname="secret_key", raise_exception=False
            )

            # Si ya existe un cliente con el email, se usara
            customers = stripe.Customer.list(
                email=self.data.payer_email
            ).auto_paging_iter()
            self.stripe_customer = next(customers, None)

            # Si no existe un cliente con el email, se crea
            if self.stripe_customer is None:
                # Crear un cliente
                self.stripe_customer = stripe.Customer.create(
                    email=self.data.payer_email,
                    name=pk_customer,
                    description="Cliente creado desde ERPNext",
                )

            # Crear y asociar un método de pago al cliente
            self.stripe_payment_method = stripe.PaymentMethod.create(
                type="card",
                card={
                    "token": self.data.stripe_token_id,
                },
            )

            # ya existe el metodo de pago en stripe?
            payment_method_exists = self.is_payment_method_attached_(
                str(self.stripe_payment_method.id), str(self.stripe_customer.id)
            )

            # Si la forma de pago no esta asociada al cliente, se asocia
            if not payment_method_exists:
                # Al cliente se le adjunta la forma de pago
                stripe.PaymentMethod.attach(
                    self.stripe_payment_method.id,
                    customer=self.stripe_customer.id,
                )

                # Registramos la tarjeta en el ERP para futuros usos
                frappe.get_doc(
                    {
                        "doctype": "PayGate Card",
                        "customer": pk_customer,
                        "token_temp": "",
                        "is_default": 1,
                        "email": self.data.payer_email,
                        "gateway": "Stripe",
                        "process_data": 0,
                        "stripe_customer_id": self.stripe_customer.id,
                        "stripe_payment_id": self.stripe_payment_method.id,
                        "card_number": "*" * 12
                        + str(self.result_stripe.get("token").get("card").get("last4")),
                        "expiration_month": self.result_stripe.get("token")
                        .get("card")
                        .get("exp_month"),
                        "expiration_year": self.result_stripe.get("token")
                        .get("card")
                        .get("exp_year"),
                        "card_brand": self.result_stripe.get("token")
                        .get("card")
                        .get("brand"),
                        "gateway_dt": "Stripe Settings",
                        "gateway_setting_name": self.name,
                    }
                ).insert(ignore_permissions=True)

            else:
                frappe.log_error(
                    title="forma pago ya existe",
                    message="forma de pago ya existe en el cliente",
                )

            return True

        except Exception:
            frappe.log_error(
                title="Stripe checkout -> attach payment method",
                message=frappe.get_traceback(),
            )

            return False

    def save_stripe_response(self) -> None:
        try:
            self.payment_req_ref = self.data.get("reference_docname")

            if self.charge.get("object") == "payment_intent":
                new_res_log = frappe.get_doc(
                    {
                        "doctype": "PayGate Response Log",
                        "gateway": "Stripe",
                        "ref_to_payment_request": self.payment_req_ref or "",
                        "payment_stripe_is_paid": 1
                        if self.charge.get("status") == "succeeded"
                        else 0,
                        "payment_stripe_id": self.charge.get("id"),
                        "amount": flt(self.charge.get("amount") / 100),
                        "amount_captured": flt(
                            self.charge.get("charges")
                            .get("data")[0]
                            .get("amount_captured")
                            / 100
                        ),
                        "amount_refunded": flt(
                            self.charge.get("charges")
                            .get("data")[0]
                            .get("amount_refunded")
                            / 100
                        ),
                        "stripe_receipt_email": self.charge.get("receipt_email"),
                        # "stripe_receipt_number": self.charge.get("receipt_number"),
                        "stripe_currency": self.charge.get("charges")
                        .get("data")[0]
                        .get("currency")
                        .upper(),
                        "stripe_receipt_url": self.charge.get("charges")
                        .get("data")[0]
                        .get("receipt_url", "/stripe/payment-ok"),
                        "stripe_response": json.dumps(
                            self.charge, indent=2, default=str
                        ),
                    }
                )
                new_res_log.insert(ignore_permissions=True)

                if self.charge.get("status") == "succeeded":
                    self.redirect_url = (
                        self.charge.get("charges")
                        .get("data")[0]
                        .get("receipt_url", "/stripe/payment-ok")
                    )

                    self.set_url_sucess_payment(
                        self.charge.get("charges")
                        .get("data")[0]
                        .get("receipt_url", "/stripe/payment-ok")
                    )
                    self.set_payment_request_as_paid(self.payment_req_ref)

                    return (
                        self.charge.get("charges")
                        .get("data")[0]
                        .get("receipt_url", "/stripe/payment-ok")
                    )

            if self.charge.get("object") == "charge":
                new_res_log = frappe.get_doc(
                    {
                        "doctype": "PayGate Response Log",
                        "gateway": "Stripe",
                        "ref_to_payment_request": self.payment_req_ref or "",
                        "payment_stripe_is_paid": self.charge.get("captured"),
                        "payment_stripe_id": self.charge.get("id"),
                        "amount": flt(self.charge.get("amount") / 100),
                        "amount_captured": flt(
                            self.charge.get("amount_captured") / 100
                        ),
                        "amount_refunded": flt(
                            self.charge.get("amount_refunded") / 100
                        ),
                        "stripe_receipt_email": self.charge.get("receipt_email"),
                        "stripe_receipt_number": self.charge.get("receipt_number"),
                        "stripe_currency": self.charge.get("currency").upper(),
                        "stripe_receipt_url": self.charge.get(
                            "receipt_url", "/stripe/payment-ok"
                        ),
                        "stripe_response": json.dumps(
                            self.charge, indent=2, default=str
                        ),
                    }
                )
                new_res_log.insert(ignore_permissions=True)

                if self.charge.get("captured"):
                    self.redirect_url = self.charge.get(
                        "receipt_url", "/stripe/payment-ok"
                    )

                    self.set_url_sucess_payment(
                        self.charge.get("receipt_url", "/stripe/payment-ok")
                    )
                    self.set_payment_request_as_paid(self.payment_req_ref)

                    return self.charge.get("receipt_url", "/stripe/payment-ok")

            return "payment-failed"

        except Exception:
            frappe.log_error(
                title="Error guardar response Stripe", message=frappe.get_traceback()
            )
            return "payment-failed"

    def set_url_sucess_payment(self, url):
        try:
            frappe.db.set_value(
                "Payment Request",
                self.payment_req_ref,
                "pay_gate_visanet_token_ok_payment",
                url,
            )
            frappe.db.commit()

        except Exception:
            frappe.log_error(
                title="Error guardar URL de pago exitoso",
                message=frappe.get_traceback(),
            )

    def set_payment_request_as_paid(self, payment_request):
        try:
            if not payment_request:
                return

            pay_req = frappe.get_doc("Payment Request", payment_request)
            pay_req.set_as_paid()

        except Exception:
            frappe.log_error(
                title=f"Error al marcar pago como exitoso {payment_request}",
                message=frappe.get_traceback(),
            )

    def is_payment_method_attached_(
        self, payment_method_id: str, customer_id: str
    ) -> bool:
        try:
            payment_methods = stripe.PaymentMethod.list(customer=customer_id)
            for pm in payment_methods.data:
                if pm.id == payment_method_id:
                    frappe.log_error(title="Ya existe", message=pm)
                    return True

            return False

        except Exception:
            frappe.log_error(
                title="Error is payment method attached", message=frappe.get_traceback()
            )
            return False


def get_gateway_controller(doctype, docname):
    reference_doc = frappe.get_doc(doctype, docname)
    gateway_controller = frappe.db.get_value(
        "Payment Gateway", reference_doc.payment_gateway, "gateway_controller"
    )
    return gateway_controller
