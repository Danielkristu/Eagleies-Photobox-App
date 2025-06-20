// static/js/poll_payment_status.js
// Polls the QRIS payment status and redirects to /payment_status on success

function pollPaymentStatus(qrId, intervalMs = 2000) {
    let pollInterval = setInterval(() => {
        fetch(`/check_qr_status/${qrId}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'payment succeed') {
                    clearInterval(pollInterval);
                    window.location.href = '/payment_status';
                }
            })
            .catch(err => {
                // Optionally handle error
                console.error('Polling error:', err);
            });
    }, intervalMs);
}

// Usage example (call this from your payment_qris.html template):
// <script>pollPaymentStatus('{{ qr_id }}');</script>
