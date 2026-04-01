document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("uploadForm");
    const overlay = document.getElementById("loadingOverlay");
    const archivoBase = document.getElementById("archivo_base");
    const archivoAware = document.getElementById("archivo_aware");

    form.addEventListener("submit", (e) => {
        if (!archivoBase.files.length || !archivoAware.files.length) {
            alert("Debes seleccionar ambos archivos antes de procesar.");
            e.preventDefault();
            return;
        }

        overlay.classList.remove("hidden");
    });
});