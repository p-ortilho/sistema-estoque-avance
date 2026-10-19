// Botão "Mostrar / Ocultar" da senha
(function () {
    var botao = document.querySelector(".mostrar-senha");
    if (!botao) return;
    var campo = document.getElementById(botao.getAttribute("aria-controls"));
    botao.addEventListener("click", function () {
        var visivel = campo.type === "text";
        campo.type = visivel ? "password" : "text";
        botao.textContent = visivel ? "Mostrar" : "Ocultar";
        botao.setAttribute("aria-pressed", String(!visivel));
        campo.focus();
    });

    // Evita clique duplo no "Entrar"
    var form = document.getElementById("login-form");
    form.addEventListener("submit", function () {
        var enviar = form.querySelector(".botao");
        enviar.disabled = true;
        enviar.textContent = "Entrando…";
    });
})();