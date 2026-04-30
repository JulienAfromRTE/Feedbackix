// Feedbackix — utilitaires globaux
document.addEventListener('DOMContentLoaded', function() {
    // Auto-dismiss flash messages apres 4 secondes
    var flashMsgs = document.querySelectorAll('.flash-msg');
    flashMsgs.forEach(function(msg) {
        setTimeout(function() {
            msg.style.transition = 'opacity 0.5s';
            msg.style.opacity = '0';
            setTimeout(function() { msg.remove(); }, 500);
        }, 4000);
    });
});
