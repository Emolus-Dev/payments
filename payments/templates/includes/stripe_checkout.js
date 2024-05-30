var stripe = Stripe("{{ publishable_key }}");

var elements = stripe.elements();

var style = {
	base: {
		color: '#32325d',
		lineHeight: '18px',
		fontFamily: '"Helvetica Neue", Helvetica, sans-serif',
		fontSmoothing: 'antialiased',
		fontSize: '16px',
		'::placeholder': {
			color: '#aab7c4'
		}
	},
	invalid: {
		color: '#fa755a',
		iconColor: '#fa755a'
	}
};

var card = elements.create('card', {
	hidePostalCode: true,
	style: style
});

card.mount('#card-element');

function setOutcome(result) {
	let save_payment_method = $('#allow_save_token').is(':checked');

	if (result.token) {
		$('#submit').prop('disabled', true)
		$('#submit').html(__('Processing...'))
		frappe.call({
			method:"payments.templates.pages.stripe_checkout.make_payment",
			freeze:true,
			headers: {"X-Requested-With": "XMLHttpRequest"},
			args: {
				"stripe_token_id": result.token.id,
				"data": JSON.stringify({{ frappe.form_dict|json }}),
				"reference_doctype": "{{ reference_doctype }}",
				"reference_docname": "{{ reference_docname }}",
				"save_payment_method": save_payment_method
			},
			callback: function(r) {
				if (r.message.status == "Completed") {
					$('#submit').hide()
					$('.success').show()
					setTimeout(function() {
						window.location.href = r.message.redirect_to
					}, 2000);

				} else {
					$('#submit').hide()
					$('.error').show()
					setTimeout(function() {
						window.location.href = r.message.redirect_to
					}, 2000);
				}
			}
		});

	} else if (result.error) {
		$('.error').html(result.error.message);
		$('.error').show()
	}
}

card.on('change', function(event) {
	var displayError = document.getElementById('card-errors');
	if (event.error) {
		displayError.textContent = event.error.message;
	} else {
		displayError.textContent = '';
	}
});

frappe.ready(function() {
	$('#submit').off("click").on("click", function(e) {
		e.preventDefault();
		var extraDetails = {
			name: $('input[name=cardholder-name]').val(),
			email: $('input[name=cardholder-email]').val()
		}
		stripe.createToken(card, extraDetails).then(function(result) {
			result.extraDetails = extraDetails;
			setOutcome(result);
		});
	})

	$('#createUser').off("click").on("click", function(e) {
		e.preventDefault();

		console.log("{{ frappe.form_dict["order_id"] }}")

		// Se envia por correo el form para que usuario resetee su contraseña,
		// se usando los datos del payment request para no tener data incorrecta
		frappe.call({
			method:"pay_gate.api.send_reset_pwd_user",
			freeze:true,
			headers: {"X-Requested-With": "XMLHttpRequest"},
			args: {
				"payment_request_ref": "{{ frappe.form_dict["order_id"] }}"
			},
			callback: function(r) {
				console.log(r)
				frappe.show_alert({
					message: __("Revisa tu correo electrónico para completar el registro."),
					indicator: 'green'
				})
			}
		});

	})
});
