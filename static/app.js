// ARCA / AFIP Facturación Electrónica - Frontend Controller v2.1.0

let appConfig = null;
let metaData = null;
let activeCbteTipo = 11; // Default: Factura C
let activeLetra = "C";
let currentLoteParsed = null;
let currentLoteId = null;

// ── UTILITIES ─────────────────────────────────────────────────────────────────

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function fmtNum(val) {
  const num = parseFloat(val) || 0;
  return num.toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getTodayStr() {
  const d = new Date();
  return d.toISOString().split("T")[0];
}

function getFirstDayOfMonthStr() {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().split("T")[0];
}

function getLastDayOfMonthStr() {
  const d = new Date();
  d.setMonth(d.getMonth() + 1);
  d.setDate(0);
  return d.toISOString().split("T")[0];
}

// ── INICIALIZACIÓN ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupComprobantePills();
  setupItemsTable();
  setupReceptorListeners();
  setupEmitirAction();
  setupModalActions();
  setupConfigForm();
  setupCsrForm();
  setupHistorialTab();
  setupCertPickers();
  setupPdfCustomization();
  setupLotesTab();

  // Fechas por defecto
  document.getElementById("op-fecha").value = getTodayStr();
  document.getElementById("op-serv-desde").value = getFirstDayOfMonthStr();
  document.getElementById("op-serv-hasta").value = getLastDayOfMonthStr();
  document.getElementById("op-vto-pago").value = getTodayStr();

  // Concepto listener
  document.getElementById("op-concepto").addEventListener("change", (e) => {
    const isService = e.target.value === "2" || e.target.value === "3";
    document.getElementById("fechas-servicio-box").classList.toggle("hidden", !isService);
  });

  await loadMeta();
  await loadConfig();
  await loadHistorial();
  await loadCertificatesList();
});

// ── TABS ──────────────────────────────────────────────────────────────────────

function setupTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");

      if (targetId === "tab-historial") {
        loadHistorial();
      } else if (targetId === "tab-config") {
        loadCertificatesList();
      }
    });
  });
}

// ── TIPO DE COMPROBANTE ───────────────────────────────────────────────────────

function setupComprobantePills() {
  const pills = document.querySelectorAll(".cbte-pill");
  const subletterBox = document.getElementById("nc-subletter-box");
  const asociadoBox = document.getElementById("asociado-box");

  pills.forEach((pill) => {
    pill.addEventListener("click", () => {
      pills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");

      const tipo = parseInt(pill.getAttribute("data-tipo"));
      const isNota = tipo === 12 || tipo === 13;

      subletterBox.classList.toggle("hidden", !isNota);
      asociadoBox.classList.toggle("hidden", !isNota);

      if (isNota) {
        const checkedRadio = document.querySelector('input[name="subletter"]:checked');
        const subletter = checkedRadio ? checkedRadio.value : "C";
        updateNotaTipo(tipo === 13 ? "NC" : "ND", subletter);
      } else {
        activeCbteTipo = tipo;
        activeLetra = pill.getAttribute("data-letra");
        updateBannerAndUI();
      }
      recalcSummary();
    });
  });

  document.querySelectorAll('input[name="subletter"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
      const activePill = document.querySelector(".cbte-pill.active");
      const tipo = parseInt(activePill.getAttribute("data-tipo"));
      updateNotaTipo(tipo === 13 ? "NC" : "ND", e.target.value);
      recalcSummary();
    });
  });
}

function updateNotaTipo(prefix, letra) {
  activeLetra = letra;
  if (prefix === "NC") {
    activeCbteTipo = letra === "A" ? 3 : letra === "B" ? 8 : 13;
  } else {
    activeCbteTipo = letra === "A" ? 2 : letra === "B" ? 7 : 12;
  }
  updateBannerAndUI();
}

function updateBannerAndUI() {
  const banner = document.getElementById("cbte-info-banner");
  const text = document.getElementById("cbte-info-text");
  const condIvaSelect = document.getElementById("receptor-cond-iva");
  const docTipoSelect = document.getElementById("receptor-doc-tipo");

  if (activeLetra === "A") {
    text.innerHTML = "<strong>Factura A:</strong> Para Responsables Inscriptos, Monotributistas o Monotributo Social / TIP (RG 5003 / 5616). Discrimina IVA por ítem.";
    banner.style.borderColor = "rgba(139, 92, 246, 0.4)";
    banner.style.color = "#C4B5FD";
    docTipoSelect.value = "80";
    if (!["1", "6", "13", "16"].includes(condIvaSelect.value)) {
      condIvaSelect.value = "1";
    }
  } else if (activeLetra === "B") {
    text.innerHTML = "<strong>Factura B:</strong> Para Consumidores Finales, Exentos, Sujetos No Categorizados o Exterior. El IVA no se discrimina.";
    banner.style.borderColor = "rgba(16, 185, 129, 0.4)";
    banner.style.color = "#6EE7B7";
    if (["1", "6", "13", "16"].includes(condIvaSelect.value)) {
      condIvaSelect.value = "5";
    }
  } else {
    text.innerHTML = "<strong>Factura C:</strong> Comprobante oficial de Monotributo / Exento para cualquier condición de cliente.";
    banner.style.borderColor = "rgba(6, 182, 212, 0.4)";
    banner.style.color = "#67E8F9";
  }

  // Consultar en vivo a AFIP el próximo número
  const currentTipo = activeCbteTipo;
  fetch(`/api/comprobantes/ultimo/${currentTipo}`)
    .then(r => r.json())
    .then(data => {
      if (data.status === "ok" && currentTipo === activeCbteTipo) {
        const ptoVta = String(data.punto_venta).padStart(4, "0");
        const prox = String(data.proximo_numero).padStart(8, "0");
        const extraSpan = document.createElement("div");
        extraSpan.style.marginTop = "6px";
        extraSpan.style.fontSize = "0.82rem";
        extraSpan.style.color = "var(--text-main)";
        extraSpan.innerHTML = `📡 <strong>AFIP Online:</strong> Próximo a emitir: <strong>${ptoVta}-${prox}</strong> (Último registrado en AFIP: #${data.ultimo_numero})`;
        text.appendChild(extraSpan);
      }
    })
    .catch(() => {});

  const isIvaVisible = activeLetra === "A" || activeLetra === "B";
  document.getElementById("th-iva-col").style.display = isIvaVisible ? "" : "none";
  document.querySelectorAll(".td-iva-col").forEach((td) => {
    td.style.display = isIvaVisible ? "" : "none";
  });
}

// ── RECEPTOR Y PADRÓN A13 ─────────────────────────────────────────────────────

function setupReceptorListeners() {
  const docInput = document.getElementById("receptor-doc-nro");
  const docTipoSelect = document.getElementById("receptor-doc-tipo");
  const condIvaSelect = document.getElementById("receptor-cond-iva");
  const btnBuscar = document.getElementById("btn-buscar-padron");

  btnBuscar.addEventListener("click", () => consultarPadron());

  docInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      consultarPadron();
    }
  });

  docInput.addEventListener("blur", () => {
    const val = docInput.value.replace(/\D/g, "");
    if (val.length === 11 && docTipoSelect.value === "80") {
      consultarPadron();
    }
  });

  docTipoSelect.addEventListener("change", (e) => {
    if (e.target.value === "99") {
      docInput.value = "";
      document.getElementById("receptor-nombre").value = "Consumidor Final";
      condIvaSelect.value = "5";
    }
  });

  condIvaSelect.addEventListener("change", (e) => {
    const val = e.target.value;
    if (val === "5" && !docInput.value.trim()) {
      docTipoSelect.value = "99";
      if (!document.getElementById("receptor-nombre").value.trim()) {
        document.getElementById("receptor-nombre").value = "Consumidor Final";
      }
    } else if (["1", "4", "6", "7", "8", "9", "10", "13", "15", "16"].includes(val)) {
      if (docTipoSelect.value === "99") {
        docTipoSelect.value = "80";
        if (document.getElementById("receptor-nombre").value === "Consumidor Final") {
          document.getElementById("receptor-nombre").value = "";
        }
      }
    }
  });
}

async function consultarPadron() {
  const docInput = document.getElementById("receptor-doc-nro");
  const cuit = docInput.value.replace(/\D/g, "");
  const feedback = document.getElementById("padron-feedback");
  const spinner = document.getElementById("padron-spinner");

  if (cuit.length !== 11) {
    feedback.textContent = "Ingrese un CUIT válido de 11 dígitos.";
    feedback.style.color = "var(--accent-rose)";
    return;
  }

  spinner.classList.remove("hidden");
  feedback.textContent = "Consultando Padrón A13 de AFIP...";
  feedback.style.color = "var(--accent-cyan)";

  try {
    const res = await fetch(`/api/padron/${cuit}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error en padrón");

    if (data.nombre) {
      document.getElementById("receptor-nombre").value = data.nombre;
      feedback.textContent = `Padrón AFIP: ${data.nombre} ✓`;
      feedback.style.color = "var(--accent-emerald)";
    }
    if (data.domicilio) {
      document.getElementById("receptor-domicilio").value = data.domicilio;
    }
  } catch (err) {
    feedback.textContent = `Advertencia: ${err.message}`;
    feedback.style.color = "var(--accent-amber)";
  } finally {
    spinner.classList.add("hidden");
  }
}

// ── ÍTEMS Y CÁLCULOS ──────────────────────────────────────────────────────────

function setupItemsTable() {
  document.getElementById("btn-add-item").addEventListener("click", () => addItemRow());
  addItemRow("Servicio de consultoría y desarrollo", 1, 0, 21);
}

function addItemRow(desc = "", qty = 1, price = 0, alic = 21) {
  const tbody = document.getElementById("items-tbody");
  const tr = document.createElement("tr");

  const isIvaVisible = activeLetra === "A" || activeLetra === "B";

  tr.innerHTML = `
    <td>
      <input type="text" class="item-desc" placeholder="Descripción del producto o servicio" value="${desc}">
    </td>
    <td>
      <input type="number" class="item-qty" min="0.01" step="0.01" value="${qty}">
    </td>
    <td>
      <input type="number" class="item-price" min="0" step="0.01" value="${price}">
    </td>
    <td class="td-iva-col" style="${isIvaVisible ? "" : "display:none;"}">
      <select class="item-iva">
        <option value="21" data-id="5" ${alic === 21 ? "selected" : ""}>21%</option>
        <option value="10.5" data-id="4" ${alic === 10.5 ? "selected" : ""}>10.5%</option>
        <option value="27" data-id="6" ${alic === 27 ? "selected" : ""}>27%</option>
        <option value="5" data-id="8" ${alic === 5 ? "selected" : ""}>5%</option>
        <option value="2.5" data-id="9" ${alic === 2.5 ? "selected" : ""}>2.5%</option>
        <option value="0" data-id="3" ${alic === 0 ? "selected" : ""}>0% (Exento)</option>
      </select>
    </td>
    <td class="subtotal-cell item-subtotal-text">$ 0,00</td>
    <td>
      <button type="button" class="btn-delete-row" title="Eliminar fila">✕</button>
    </td>
  `;

  tr.querySelectorAll("input, select").forEach((el) => {
    el.addEventListener("input", recalcSummary);
    el.addEventListener("change", recalcSummary);
  });

  tr.querySelector(".btn-delete-row").addEventListener("click", () => {
    if (tbody.children.length > 1) {
      tr.remove();
      recalcSummary();
    } else {
      showToast("Debe haber al menos un ítem en la factura.", "info");
    }
  });

  tbody.appendChild(tr);
  recalcSummary();
}

function recalcSummary() {
  const rows = document.querySelectorAll("#items-tbody tr");
  let subtotalNeto = 0;
  let totalIva = 0;
  const ivaGroups = {};

  rows.forEach((tr) => {
    const qty = parseFloat(tr.querySelector(".item-qty").value) || 0;
    const price = parseFloat(tr.querySelector(".item-price").value) || 0;
    const ivaSelect = tr.querySelector(".item-iva");
    const ivaPorc = parseFloat(ivaSelect.value) || 0;

    const rowNeto = qty * price;
    let rowIva = 0;
    if (activeLetra === "A" || activeLetra === "B") {
      rowIva = rowNeto * (ivaPorc / 100);
      if (!ivaGroups[ivaPorc]) ivaGroups[ivaPorc] = 0;
      ivaGroups[ivaPorc] += rowIva;
    }

    subtotalNeto += rowNeto;
    totalIva += rowIva;

    const subtotalText = tr.querySelector(".item-subtotal-text");
    subtotalText.textContent = `$ ${fmtNum(rowNeto)}`;
  });

  const total = subtotalNeto + totalIva;

  document.getElementById("summary-subtotal").textContent = `$ ${fmtNum(subtotalNeto)}`;
  document.getElementById("summary-total").textContent = `$ ${fmtNum(total)}`;

  const ivaRow = document.getElementById("summary-iva-row");
  const ivaBreakdown = document.getElementById("summary-iva-breakdown");

  if (activeLetra === "A" || activeLetra === "B") {
    ivaRow.style.display = "flex";
    document.getElementById("summary-iva").textContent = `$ ${fmtNum(totalIva)}`;

    let breakdownHtml = "";
    for (const [porc, monto] of Object.entries(ivaGroups)) {
      if (monto > 0) {
        breakdownHtml += `
          <div class="breakdown-row">
            <span>Alícuota ${porc}%:</span>
            <span>$ ${fmtNum(monto)}</span>
          </div>
        `;
      }
    }
    ivaBreakdown.innerHTML = breakdownHtml;
    ivaBreakdown.style.display = breakdownHtml ? "block" : "none";
  } else {
    ivaRow.style.display = "none";
    ivaBreakdown.style.display = "none";
  }
}

// ── EMITIR FACTURA ────────────────────────────────────────────────────────────

function setupEmitirAction() {
  const btnEmitir = document.getElementById("btn-emitir-factura");
  btnEmitir.addEventListener("click", async () => {
    await emitirFactura();
  });
}

async function emitirFactura() {
  const btnEmitir = document.getElementById("btn-emitir-factura");
  const spinner = document.getElementById("emitir-spinner");

  const docTipo = parseInt(document.getElementById("receptor-doc-tipo").value);
  const docNro = document.getElementById("receptor-doc-nro").value.trim();
  const nombre = document.getElementById("receptor-nombre").value.trim();

  if (activeLetra === "A" && docTipo !== 80) {
    showToast("Para Factura A debe ingresar el CUIT del receptor.", "error");
    return;
  }
  if (!nombre) {
    showToast("Debe ingresar el nombre o razón social del cliente.", "error");
    return;
  }

  const rows = document.querySelectorAll("#items-tbody tr");
  const items = [];
  rows.forEach((tr) => {
    const desc = tr.querySelector(".item-desc").value.trim();
    const qty = parseFloat(tr.querySelector(".item-qty").value) || 0;
    const price = parseFloat(tr.querySelector(".item-price").value) || 0;
    const ivaSelect = tr.querySelector(".item-iva");
    const ivaPorc = parseFloat(ivaSelect.value) || 0;
    const ivaId = parseInt(ivaSelect.selectedOptions[0].getAttribute("data-id")) || 5;

    if (desc && qty > 0) {
      items.push({
        descripcion: desc,
        cantidad: qty,
        precio_unitario: price,
        alicuota_iva: ivaPorc,
        alicuota_iva_id: ivaId,
      });
    }
  });

  if (items.length === 0) {
    showToast("Debe ingresar al menos un ítem con descripción y cantidad.", "error");
    return;
  }

  const condIvaVal = document.getElementById("receptor-cond-iva").value;
  if (!condIvaVal) {
    showToast("Por favor seleccione la condición frente al IVA del cliente.", "error");
    return;
  }

  const payload = {
    cbte_tipo: activeCbteTipo,
    doc_tipo: docTipo,
    cuit_cliente: docTipo === 99 ? "0" : docNro,
    nombre_cliente: nombre,
    concepto_afip: parseInt(document.getElementById("op-concepto").value),
    condicion_iva_receptor: parseInt(condIvaVal),
    condicion_venta: document.getElementById("op-cond-venta").value,
    fecha: document.getElementById("op-fecha").value.replace(/-/g, ""),
    periodo_desde: document.getElementById("op-serv-desde").value.replace(/-/g, ""),
    periodo_hasta: document.getElementById("op-serv-hasta").value.replace(/-/g, ""),
    fecha_vto_pago: document.getElementById("op-vto-pago").value.replace(/-/g, ""),
    items: items,
    duplicado: document.getElementById("chk-duplicado").checked,
    dry_run: document.getElementById("chk-dry-run").checked,
  };

  if (document.getElementById("asociado-box").classList.contains("hidden") === false) {
    payload.numero_original = parseInt(document.getElementById("op-cbte-asoc-nro").value) || null;
    payload.cbte_tipo_original = parseInt(document.getElementById("op-cbte-asoc-tipo").value) || null;
  }

  btnEmitir.disabled = true;
  spinner.classList.remove("hidden");

  try {
    const res = await fetch("/api/comprobantes/emitir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error al emitir comprobante");

    if (payload.dry_run) {
      showToast("Simulación exitosa (Dry-Run): PDF de prueba generado.", "success");
      openPdfModal(data);
      return;
    }

    showToast(`Comprobante ${data.comprobante} emitido con éxito!`, "success");
    openPdfModal(data);
    loadHistorial();
  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    btnEmitir.disabled = false;
    spinner.classList.add("hidden");
  }
}

// ── MODAL VISOR PDF ───────────────────────────────────────────────────────────

function setupModalActions() {
  const modal = document.getElementById("modal-pdf");
  const btnClose = document.getElementById("btn-close-modal");
  const btnPrint = document.getElementById("btn-print-modal");

  btnClose.addEventListener("click", () => modal.classList.add("hidden"));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.classList.add("hidden");
  });

  btnPrint.addEventListener("click", () => {
    const iframe = document.getElementById("pdf-viewer-frame");
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.focus();
      iframe.contentWindow.print();
    }
  });

  const btnRegenModal = document.getElementById("btn-regenerate-modal");
  if (btnRegenModal) {
    btnRegenModal.addEventListener("click", async () => {
      if (!currentModalCbte || !currentModalCbte.numero) {
        showToast("Este comprobante de prueba no requiere regeneración.", "info");
        return;
      }
      showToast("Regenerando PDF con el logo y diseño actual...", "info");
      try {
        const res = await fetch("/api/comprobantes/reimprimir", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cbte_tipo: currentModalCbte.cbte_tipo || (currentModalCbte.tipo === "A" ? 1 : (currentModalCbte.tipo === "B" ? 6 : 11)),
            numero: currentModalCbte.numero,
            punto_venta: currentModalCbte.punto_venta || 4,
            duplicado: false,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Error reimprimiendo comprobante");

        const iframe = document.getElementById("pdf-viewer-frame");
        const pdfUrl = `/api/pdf/${data.pdf_filename}?t=${Date.now()}`;
        iframe.src = pdfUrl;
        document.getElementById("btn-download-pdf").href = pdfUrl;
        showToast("¡PDF actualizado con el nuevo diseño y logo!", "success");
      } catch (err) {
        showToast(`Error: ${err.message}`, "error");
      }
    });
  }
}

let currentModalCbte = null;

function openPdfModal(cbteData) {
  currentModalCbte = cbteData;
  const modal = document.getElementById("modal-pdf");
  const title = document.getElementById("modal-pdf-title");
  const subtitle = document.getElementById("modal-pdf-subtitle");
  const iframe = document.getElementById("pdf-viewer-frame");
  const btnDownload = document.getElementById("btn-download-pdf");

  title.textContent = `${cbteData.tipo} N° ${cbteData.comprobante}`;
  subtitle.textContent = `CAE: ${cbteData.cae} ${cbteData.cae_vencimiento ? '| Vencimiento: ' + cbteData.cae_vencimiento : ''}`;

  const pdfUrl = `/api/pdf/${cbteData.pdf_filename}?t=${Date.now()}`;
  iframe.src = pdfUrl;
  btnDownload.href = pdfUrl;
  btnDownload.download = cbteData.pdf_filename;

  modal.classList.remove("hidden");
}

// ── FACTURACIÓN POR LOTES (CSV) ───────────────────────────────────────────────

function setupLotesTab() {
  const dropzone = document.getElementById("csv-dropzone");
  const fileInput = document.getElementById("csv-file-input");
  const btnSelect = document.getElementById("btn-select-csv");
  const btnEmitirLote = document.getElementById("btn-emitir-lote");

  btnSelect.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("click", (e) => {
    if (e.target !== btnSelect) fileInput.click();
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      handleCsvFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) {
      handleCsvFile(e.target.files[0]);
    }
  });

  btnEmitirLote.addEventListener("click", () => emitirLoteActual());
  const selectModo = document.getElementById("select-lote-modo");
  const fallbackChk = document.getElementById("chk-lote-dryrun");
  if (selectModo && fallbackChk) {
    selectModo.addEventListener("change", () => {
      fallbackChk.checked = (selectModo.value === "dryrun");
    });
  }

}

async function handleCsvFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  showToast(`Interpretando lote ${file.name}...`, "info");

  try {
    const res = await fetch("/api/lotes/parse-csv", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    currentLoteParsed = data;
    renderLoteStats(data.totales);
    renderLoteTable(data.rows);

    document.getElementById("card-lote-preview").classList.remove("hidden");
    document.getElementById("lote-stats-bar").classList.remove("hidden");
    showToast(`Lote interpretado: ${data.totales.count} comprobantes encontrados.`, "success");
  } catch (err) {
    showToast(`Error al leer CSV: ${err.message}`, "error");
  }
}

function renderLoteStats(tot) {
  document.getElementById("stat-total-cbtes").textContent = tot.count;
  document.getElementById("stat-total-monto").textContent = `$ ${fmtNum(tot.monto)}`;
  document.getElementById("stat-validos").textContent = tot.validos;
  document.getElementById("stat-errores").textContent = tot.errores;

  const pillsContainer = document.getElementById("stat-tipos-pills");
  pillsContainer.innerHTML = `
    <span class="badge" style="background:rgba(139,92,246,0.2); color:#C4B5FD;">A: ${tot.tipo_a}</span>
    <span class="badge" style="background:rgba(16,185,129,0.2); color:#6EE7B7;">B: ${tot.tipo_b}</span>
    <span class="badge" style="background:rgba(6,182,212,0.2); color:#67E8F9;">C: ${tot.tipo_c}</span>
  `;

  const statAfip = document.getElementById("stat-afip-ultimo");
  if (statAfip) {
    Promise.all([
      fetch("/api/comprobantes/ultimo/6").then(r => r.json()).catch(() => null),
      fetch("/api/comprobantes/ultimo/1").then(r => r.json()).catch(() => null)
    ]).then(([resB, resA]) => {
      if (resB && resB.status === "ok") {
        const uB = resB.ultimo_numero;
        const uA = resA && resA.status === "ok" ? resA.ultimo_numero : "-";
        statAfip.innerHTML = `PV ${resB.punto_venta} → B: <strong>#${uB}</strong> | A: <strong>#${uA}</strong>`;
      } else {
        statAfip.textContent = "No disponible";
      }
    });
  }
}

function renderLoteTable(rows) {
  const tbody = document.getElementById("tbody-lote-preview");
  tbody.innerHTML = "";

  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.id = `lote-row-${r.index}`;

    let statusBadge = "";
    if (r.cae) {
      statusBadge = `<span class="badge badge-ok" style="background:#10B981; color:#fff;">Emitido ✓ (${r.comprobante})</span> ${r.pdf_filename ? `<a href="/api/comprobantes/download-pdf/${r.pdf_filename}" target="_blank" class="btn btn-sm btn-secondary" style="padding:1px 6px; font-size:0.75rem; margin-left:4px;">PDF</a>` : ""}`;
    } else if (r.status === "valido") {
      statusBadge = '<span class="badge badge-ok">Válido ✓</span>';
    } else if (r.status === "advertencia") {
      statusBadge = `<span class="badge badge-warn" title="${r.warnings.join('; ')}">Advertencia ⚠️</span>`;
    } else {
      statusBadge = `<span class="badge badge-err" title="${r.errors.join('; ')}">Error ✕</span>`;
    }

    const tipoBadge = `<span class="pill-letter letter-${r.tipo.toLowerCase()}" style="width:24px;height:24px;font-size:0.75rem;display:inline-flex;">${r.tipo}</span>`;

    tr.innerHTML = `
      <td class="mono-cell">${r.index}</td>
      <td>${tipoBadge}</td>
      <td class="mono-cell">${r.cuit_cliente}</td>
      <td>${r.nombre_cliente}</td>
      <td><small>${r.concepto}</small></td>
      <td class="mono-cell">$ ${fmtNum(r.neto)}</td>
      <td class="mono-cell">${r.alicuota_iva > 0 ? `$ ${fmtNum(r.iva)} (${r.alicuota_iva}%)` : '-'}</td>
      <td class="mono-cell"><strong>$ ${fmtNum(r.monto)}</strong></td>
      <td class="row-status-cell">${statusBadge}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function emitirLoteActual() {
  if (!currentLoteParsed || !currentLoteParsed.rows.length) {
    showToast("No hay filas cargadas para emitir.", "error");
    return;
  }

  const modoSelect = document.getElementById("select-lote-modo");
  const chkDryRun = document.getElementById("chk-lote-dryrun");
  let modo = "homo";
  if (modoSelect) {
    modo = modoSelect.value;
  } else if (chkDryRun && chkDryRun.checked) {
    modo = "dryrun";
  }

  const dryRun = (modo === "dryrun");
  const env = (modo === "prod") ? "prod" : "homo";
  const duplicado = document.getElementById("chk-lote-duplicado")?.checked ?? false;

  const yaEmitidos = currentLoteParsed.rows.filter(r => r.cae && r.cae.trim()).length;
  const pendientesCount = currentLoteParsed.rows.length - yaEmitidos;
  const infoLote = yaEmitidos > 0 
    ? `(${pendientesCount} comprobantes pendientes, ${yaEmitidos} ya emitidos que se omitirán)`
    : `(${currentLoteParsed.rows.length} comprobantes)`;

  let confirmMsg = "";
  if (modo === "dryrun") {
    confirmMsg = `🧪 MODO SIMULACIÓN LOCAL (DRY-RUN)\n\n¿Desea iniciar la simulación de ${currentLoteParsed.rows.length} comprobantes?\n\n• NO se contactará a AFIP.\n• No tiene costo ni impacto alguno.\n• Genera comprobantes y PDFs ficticios para previsualizar.`;
  } else if (modo === "homo") {
    confirmMsg = `🔬 MODO AFIP HOMOLOGACIÓN (TESTING REAL)\n\n¿Desea emitir en AFIP HOMOLOGACIÓN ${infoLote}?\n\n✓ Servidor de prueba: wswhomo.afip.gov.ar\n✓ Certificados de prueba (Homo)\n✓ Se obtendrán CAEs reales de prueba otorgados por AFIP\n✓ NO TIENE NINGÚN IMPACTO FISCAL NI LEGAL.\n\n¿Desea continuar?`;
  } else {
    confirmMsg = `🔴 ATENCIÓN CRÍTICA: MODO PRODUCCIÓN OFICIAL\n\nEstá a punto de emitir ${infoLote} en AFIP PRODUCCIÓN.\n\n⚠️ ¡ESTOS COMPROBANTES SON OFICIALES Y TIENEN IMPACTO FISCAL REAL!\n⚠️ No se pueden borrar una vez autorizados por AFIP.\n\n¿Está completamente seguro de continuar con PRODUCCIÓN?`;
  }

  if (!confirm(confirmMsg)) return;

  const btnEmitir = document.getElementById("btn-emitir-lote");
  const spinner = document.getElementById("lote-spinner");
  const progressBox = document.getElementById("lote-progress-box");
  const progressFill = document.getElementById("lote-progress-fill");
  const progressText = document.getElementById("lote-progress-text");
  const progressPercent = document.getElementById("lote-progress-percent");

  btnEmitir.disabled = true;
  spinner.classList.remove("hidden");
  progressBox.classList.remove("hidden");
  progressFill.style.width = "10%";
  progressPercent.textContent = "Iniciando...";

  try {
    const payload = {
      rows: currentLoteParsed.rows,
      env: env,
      dry_run: dryRun,
      duplicado: duplicado,
    };

    const res = await fetch("/api/lotes/emitir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    progressFill.style.width = "100%";
    progressPercent.textContent = "100%";
    progressText.textContent = `Lote finalizado: ${data.exitosos} exitosos, ${data.fallidos} fallidos.`;

    currentLoteId = data.lote_id;

    // Guardar estado en memoria para no duplicar si reintenta
    data.resultados.forEach((resItem) => {
      const targetRowObj = currentLoteParsed.rows.find(r => String(r.index) === String(resItem.index));
      if (targetRowObj && resItem.status === "ok") {
        targetRowObj.cae = resItem.cae;
        targetRowObj.comprobante = resItem.comprobante;
        targetRowObj.status = "ok";
      }

      const row = document.getElementById(`lote-row-${resItem.index}`);
      if (row) {
        const statusCell = row.querySelector(".row-status-cell");
        if (resItem.status === "ok") {
          statusCell.innerHTML = `
            <span class="badge badge-ok">Emitido ✓ (${resItem.comprobante})</span>
            ${resItem.pdf_filename ? `<button class="btn btn-secondary btn-sm" style="margin-left:0.5rem;" onclick="openPdfByName('${resItem.pdf_filename}')">PDF</button>` : ''}
          `;
        } else {
          statusCell.innerHTML = `<span class="badge badge-err" title="${resItem.error}">Falló: ${resItem.error}</span>`;
        }
      }
    });

    if (data.exitosos > 0) {
      const zipBtn = document.getElementById("btn-download-lote-zip");
      zipBtn.href = `/api/lotes/download-zip/${data.lote_id}`;
      if (dryRun) {
        zipBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Descargar Lote Simulado (ZIP)
        `;
      } else {
        zipBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          Descargar Todos los Comprobantes (ZIP)
        `;
      }
      document.getElementById("lote-final-actions").classList.remove("hidden");
    }

    showToast(`Procesamiento finalizado (${data.exitosos} exitosos, ${data.fallidos} fallidos).`, "success");
    loadHistorial();
  } catch (err) {
    showToast(`Error al procesar lote: ${err.message}`, "error");
  } finally {
    btnEmitir.disabled = false;
    spinner.classList.add("hidden");
  }
}

function openPdfByName(pdfFilename) {
  openPdfModal({
    tipo: "Comprobante",
    comprobante: pdfFilename,
    cae: "Lote Emitido",
    cae_vencimiento: "",
    pdf_filename: pdfFilename,
  });
}

// ── SELECTOR DE CERTIFICADOS Y SUBIDA ─────────────────────────────────────────

let cachedCerts = [];

async function loadCertificatesList() {
  try {
    const res = await fetch("/api/certs/list");
    cachedCerts = await res.json();
    populateCertDropdowns();
  } catch (err) {
    console.error("Error cargando certificados:", err);
  }
}

function populateCertDropdowns() {
  const dropdownIds = [
    { id: "select-cert-homo", inputId: "cfg-cert-homo", filterType: "cert", env: "homo" },
    { id: "select-key-homo", inputId: "cfg-key-homo", filterType: "key", env: "homo" },
    { id: "select-cert-prod", inputId: "cfg-cert-prod", filterType: "cert", env: "prod" },
    { id: "select-key-prod", inputId: "cfg-key-prod", filterType: "key", env: "prod" },
  ];

  dropdownIds.forEach(({ id, inputId, filterType }) => {
    const select = document.getElementById(id);
    if (!select) return;

    select.innerHTML = `<option value="">-- Seleccionar archivo detectado en ./certs --</option>`;

    cachedCerts.forEach((c) => {
      // Mostrar primero los compatibles
      const isCompat = c.type === filterType;
      const opt = document.createElement("option");
      opt.value = `./${c.path}`;
      opt.textContent = `${c.name} (${c.path})`;
      if (isCompat) {
        select.appendChild(opt);
      }
    });

    const currentVal = document.getElementById(inputId).value;
    if (currentVal) {
      select.value = currentVal;
    }

    select.addEventListener("change", (e) => {
      if (e.target.value) {
        document.getElementById(inputId).value = e.target.value;
        showToast(`Seleccionado: ${e.target.value}`, "info");
      }
    });
  });
}

function setupCertPickers() {
  const uploader = document.getElementById("cert-file-uploader");
  let activeTargetInputId = null;
  let activeTargetEnv = "";

  document.querySelectorAll(".btn-upload-trigger").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTargetInputId = btn.getAttribute("data-target");
      activeTargetEnv = btn.getAttribute("data-env");
      uploader.click();
    });
  });

  uploader.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];

    const formData = new FormData();
    formData.append("file", file);
    formData.append("target_subfolder", activeTargetEnv === "homo" ? "homo" : "");

    showToast(`Subiendo ${file.name} a certs/...`, "info");

    try {
      const res = await fetch("/api/upload-cert", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);

      const relPath = `./${data.path}`;
      document.getElementById(activeTargetInputId).value = relPath;
      showToast(`Archivo guardado: ${relPath}`, "success");

      await loadCertificatesList();
      await loadConfig();
    } catch (err) {
      showToast(`Error subiendo certificado: ${err.message}`, "error");
    } finally {
      uploader.value = "";
    }
  });
}

// ── PERSONALIZACIÓN DE PDF ───────────────────────────────────────────────────

function setupPdfCustomization() {
  const btnUploadLogo = document.getElementById("btn-upload-logo");
  const logoInput = document.getElementById("logo-file-input");
  const logoPathInput = document.getElementById("cfg-logo-path");
  const logoPreviewBox = document.getElementById("logo-preview-box");

  const btnUploadWm = document.getElementById("btn-upload-watermark");
  const wmInput = document.getElementById("watermark-file-input");
  const wmPathInput = document.getElementById("cfg-watermark-image");

  btnUploadLogo.addEventListener("click", () => logoInput.click());
  logoInput.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const formData = new FormData();
    formData.append("file", e.target.files[0]);
    formData.append("asset_type", "logo");

    try {
      const res = await fetch("/api/upload-asset", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);

      logoPathInput.value = `./${data.path}`;
      logoPreviewBox.innerHTML = `<img src="${data.url}" alt="Logo preview">`;
      try { await saveConfig(); } catch (e) {}
      showToast("Logo subido y guardado correctamente.", "success");
    } catch (err) {
      showToast(`Error subiendo logo: ${err.message}`, "error");
    }
  });

  btnUploadWm.addEventListener("click", () => wmInput.click());
  wmInput.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const formData = new FormData();
    formData.append("file", e.target.files[0]);
    formData.append("asset_type", "watermark");

    try {
      const res = await fetch("/api/upload-asset", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);

      wmPathInput.value = `./${data.path}`;
      try { await saveConfig(); } catch (e) {}
      showToast("Imagen de marca de agua subida y guardada.", "success");
    } catch (err) {
      showToast(`Error subiendo watermark: ${err.message}`, "error");
    }
  });

  // Previsualizar Factura de Ejemplo
  document.getElementById("btn-preview-sample-pdf").addEventListener("click", async () => {
    showToast("Generando factura de prueba con el diseño actual...", "info");
    try {
      const payload = {
        logo_path: document.getElementById("cfg-logo-path").value.trim(),
        ingresos_brutos: document.getElementById("cfg-ingresos-brutos").value.trim(),
        razon_social: document.getElementById("cfg-razon-social").value.trim(),
        domicilio: document.getElementById("cfg-domicilio").value.trim(),
        condicion_iva_emisor: document.getElementById("cfg-cond-iva-emisor").value,
        inicio_actividades: document.getElementById("cfg-inicio-actividades").value.trim(),
        leyenda: document.getElementById("cfg-leyenda").value.trim(),
        watermark_text: document.getElementById("cfg-watermark-text").value.trim(),
        watermark_image: document.getElementById("cfg-watermark-image").value.trim(),
      };
      const res = await fetch("/api/pdf/preview-sample", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);

      openPdfModal({
        tipo: "Factura A (Modelo de Prueba)",
        comprobante: "0004-00009999",
        cae: "74251829304918",
        cae_vencimiento: "EJEMPLO",
        pdf_filename: data.pdf_filename,
      });
    } catch (err) {
      showToast(`Error generando preview: ${err.message}`, "error");
    }
  });
}

// ── HISTORIAL ─────────────────────────────────────────────────────────────────

function setupHistorialTab() {
  document.getElementById("btn-refresh-historial").addEventListener("click", loadHistorial);
  document.getElementById("historial-search").addEventListener("input", filterHistorial);

  document.getElementById("btn-consultar-afip").addEventListener("click", consultarComprobanteAfip);
  document.getElementById("btn-reimprimir-afip").addEventListener("click", reimprimirComprobanteAfip);
}

let cachedHistorial = [];

async function loadHistorial() {
  try {
    const res = await fetch("/api/comprobantes/historial");
    cachedHistorial = await res.json();
    renderHistorial(cachedHistorial);
  } catch (err) {
    console.error("Error cargando historial:", err);
  }
}

function renderHistorial(list) {
  const tbody = document.getElementById("historial-tbody");
  tbody.innerHTML = "";

  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-dim); padding:2rem;">No hay comprobantes emitidos aún.</td></tr>`;
    return;
  }

  list.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="mono-cell"><strong>${item.comprobante || "-"}</strong></td>
      <td><span class="badge badge-pv">${item.tipo || "Factura"}</span></td>
      <td>${item.fecha || "-"}</td>
      <td>${item.cliente || "Consumidor Final"}</td>
      <td class="mono-cell">$ ${fmtNum(item.monto)}</td>
      <td class="mono-cell">${item.cae || "-"}</td>
      <td>
        <button class="btn btn-secondary btn-sm btn-ver-pdf" data-filename="${item.pdf_filename || ""}">
          Ver / Imprimir
        </button>
      </td>
    `;

    tr.querySelector(".btn-ver-pdf").addEventListener("click", () => {
      if (item.pdf_filename) {
        openPdfModal(item);
      } else {
        showToast("PDF no disponible localmente.", "error");
      }
    });

    tbody.appendChild(tr);
  });
}

function filterHistorial(e) {
  const q = e.target.value.toLowerCase();
  const filtered = cachedHistorial.filter((item) => {
    return (
      (item.comprobante && item.comprobante.toLowerCase().includes(q)) ||
      (item.cliente && item.cliente.toLowerCase().includes(q)) ||
      (item.cuit_cliente && item.cuit_cliente.includes(q))
    );
  });
  renderHistorial(filtered);
}

async function consultarComprobanteAfip() {
  const tipo = document.getElementById("consultar-tipo").value;
  const nro = document.getElementById("consultar-numero").value;
  const resultBox = document.getElementById("consulta-afip-result");

  if (!nro) {
    showToast("Ingrese el número de comprobante a consultar.", "error");
    return;
  }

  resultBox.classList.remove("hidden");
  resultBox.innerHTML = "Consultando en AFIP...";

  try {
    const res = await fetch(`/api/comprobantes/consultar/${tipo}/${nro}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    resultBox.innerHTML = `
      <div><strong>Comprobante:</strong> ${data.tipo_nombre} N° ${data.numero} (Pto. Venta: ${data.punto_venta})</div>
      <div><strong>Fecha de Emisión:</strong> ${data.fecha}</div>
      <div><strong>CAE Autorizado:</strong> ${data.cae} (Vence: ${data.cae_vencimiento})</div>
      <div><strong>Doc. Receptor:</strong> Tipo ${data.doc_tipo} - ${data.doc_nro}</div>
      <div><strong>Importe Total:</strong> $ ${fmtNum(data.monto)}</div>
      ${data.imp_neto ? `<div><strong>Importe Neto:</strong> $ ${fmtNum(data.imp_neto)}</div>` : ""}
      ${data.imp_iva ? `<div><strong>Importe IVA:</strong> $ ${fmtNum(data.imp_iva)}</div>` : ""}
    `;
  } catch (err) {
    resultBox.innerHTML = `<span style="color:var(--accent-rose);">Error: ${err.message}</span>`;
  }
}

async function reimprimirComprobanteAfip() {
  const tipo = parseInt(document.getElementById("consultar-tipo").value);
  const nro = parseInt(document.getElementById("consultar-numero").value);

  if (!nro) {
    showToast("Ingrese el número de comprobante para reimprimir.", "error");
    return;
  }

  showToast("Generando PDF desde AFIP...", "info");

  try {
    const res = await fetch("/api/comprobantes/reimprimir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cbte_tipo: tipo, numero: nro, duplicado: false }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    openPdfModal({
      tipo: `Comprobante`,
      comprobante: `${nro}`,
      cae: "Consultado en AFIP",
      cae_vencimiento: "",
      pdf_filename: data.pdf_filename,
    });
  } catch (err) {
    showToast(`Error al reimprimir: ${err.message}`, "error");
  }
}

// ── CONFIGURACIÓN & TEST ──────────────────────────────────────────────────────

async function loadMeta() {
  try {
    const res = await fetch("/api/meta");
    metaData = await res.json();
  } catch (err) {
    console.error("Error cargando metadatos:", err);
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    appConfig = await res.json();

    document.getElementById("header-emisor-summary").textContent = 
      `${appConfig.razon_social || "Emisor no configurado"} (CUIT: ${appConfig.cuit || "--"})`;
    document.getElementById("badge-punto-venta").textContent = `PV: ${String(appConfig.punto_venta).padStart(4, "0")}`;
    
    const envPill = document.getElementById("btn-toggle-env-header");
    const envLabel = document.getElementById("env-label");
    if (appConfig.env === "prod") {
      envPill.classList.add("prod");
      envLabel.textContent = "PRODUCCIÓN";
    } else {
      envPill.classList.remove("prod");
      envLabel.textContent = "HOMO";
    }

    document.getElementById("summary-pv").textContent = String(appConfig.punto_venta).padStart(4, "0");
    document.getElementById("summary-env").textContent = appConfig.env.toUpperCase();

    // Rellenar formulario de configuración
    document.getElementById("cfg-env").value = appConfig.env;
    document.getElementById("cfg-punto-venta").value = appConfig.punto_venta;
    document.getElementById("cfg-cuit").value = appConfig.cuit;
    document.getElementById("cfg-razon-social").value = appConfig.razon_social;
    document.getElementById("cfg-nombre-fantasia").value = appConfig.nombre_fantasia;
    document.getElementById("cfg-domicilio").value = appConfig.domicilio;
    document.getElementById("cfg-cond-iva-emisor").value = appConfig.condicion_iva_emisor || "Responsable Monotributo";
    document.getElementById("cfg-ingresos-brutos").value = appConfig.ingresos_brutos;
    document.getElementById("cfg-inicio-actividades").value = appConfig.inicio_actividades;
    document.getElementById("cfg-limite-cf").value = appConfig.limite_cf;

    document.getElementById("cfg-cert-homo").value = appConfig.cert_path_homo;
    document.getElementById("cfg-key-homo").value = appConfig.key_path_homo;
    document.getElementById("cfg-cert-prod").value = appConfig.cert_path_prod;
    document.getElementById("cfg-key-prod").value = appConfig.key_path_prod;

    document.getElementById("cfg-logo-path").value = appConfig.logo_path || "";
    document.getElementById("cfg-leyenda").value = appConfig.leyenda || "";
    document.getElementById("cfg-watermark-text").value = appConfig.watermark_text || "";
    document.getElementById("cfg-watermark-image").value = appConfig.watermark_image || "";

    if (appConfig.logo_path) {
      document.getElementById("logo-preview-box").innerHTML = `<img src="${appConfig.logo_path}" alt="Logo">`;
    }

    updateCertBadges(appConfig);
  } catch (err) {
    console.error("Error cargando configuración:", err);
  }
}

function updateCertBadges(cfg) {
  setCertBadge("badge-cert-homo", cfg.cert_homo_exists);
  setCertBadge("badge-key-homo", cfg.key_homo_exists);
  setCertBadge("badge-cert-prod", cfg.cert_prod_exists);
  setCertBadge("badge-key-prod", cfg.key_prod_exists);
}

function setCertBadge(id, exists) {
  const el = document.getElementById(id);
  if (!el) return;
  if (exists) {
    el.className = "badge badge-ok";
    el.textContent = "Existe ✓";
  } else {
    el.className = "badge badge-err";
    el.textContent = "No Encontrado ✕";
  }
}

function setupConfigForm() {
  document.getElementById("form-config").addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveConfig();
  });

  document.getElementById("btn-test-conexion").addEventListener("click", testConexion);
  document.getElementById("btn-quick-test").addEventListener("click", testConexion);

  document.getElementById("btn-toggle-env-header").addEventListener("click", async () => {
    const nextEnv = appConfig.env === "prod" ? "homo" : "prod";
    const confirmChange = confirm(`¿Desea cambiar el entorno activo a ${nextEnv.toUpperCase()}?`);
    if (confirmChange) {
      document.getElementById("cfg-env").value = nextEnv;
      await saveConfig();
    }
  });
}

async function saveConfig() {
  const payload = {
    env: document.getElementById("cfg-env").value,
    punto_venta: parseInt(document.getElementById("cfg-punto-venta").value),
    cuit: document.getElementById("cfg-cuit").value.trim(),
    razon_social: document.getElementById("cfg-razon-social").value.trim(),
    nombre_fantasia: document.getElementById("cfg-nombre-fantasia").value.trim(),
    domicilio: document.getElementById("cfg-domicilio").value.trim(),
    condicion_iva_emisor: document.getElementById("cfg-cond-iva-emisor").value,
    logo_path: document.getElementById("cfg-logo-path").value.trim(),
    leyenda: document.getElementById("cfg-leyenda").value.trim(),
    watermark_text: document.getElementById("cfg-watermark-text").value.trim(),
    watermark_image: document.getElementById("cfg-watermark-image").value.trim(),
    ingresos_brutos: document.getElementById("cfg-ingresos-brutos").value.trim(),
    inicio_actividades: document.getElementById("cfg-inicio-actividades").value.trim(),
    limite_cf: parseFloat(document.getElementById("cfg-limite-cf").value) || 97673.32,
    cert_path_homo: document.getElementById("cfg-cert-homo").value.trim(),
    key_path_homo: document.getElementById("cfg-key-homo").value.trim(),
    cert_path_prod: document.getElementById("cfg-cert-prod").value.trim(),
    key_path_prod: document.getElementById("cfg-key-prod").value.trim(),
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    showToast("Configuración guardada correctamente.", "success");
    await loadConfig();
  } catch (err) {
    showToast(`Error guardando configuración: ${err.message}`, "error");
  }
}

async function testConexion() {
  const body = document.getElementById("diagnosis-body");
  body.innerHTML = `
    <div style="display:flex; align-items:center; gap:0.5rem; color:var(--accent-cyan);">
      <span class="spinner"></span> Conectando con WSAA y WSFEv1 de AFIP...
    </div>
  `;

  try {
    const res = await fetch("/api/config/test");
    const data = await res.json();

    if (res.ok) {
      body.innerHTML = `
        <div style="color:var(--accent-emerald); font-weight:600; margin-bottom:0.75rem;">
          ✓ Conexión Exitosa con AFIP (${data.env.toUpperCase()})
        </div>
        <ul style="list-style:none; line-height:1.8; font-size:0.875rem;">
          <li><strong>WSAA (Autenticación):</strong> ${data.wsaa_status} (${data.wsaa_tiempo_ms} ms)</li>
          <li><strong>WSFEv1 (Facturación):</strong> ${data.wsfe_status} (${data.wsfe_tiempo_ms} ms)</li>
          <li><strong>Punto de Venta:</strong> ${data.punto_venta}</li>
          <li><strong>Última Factura C Emitida:</strong> N° ${data.ultimo_factura_c}</li>
          <li><strong>Próximo Número a Emitir:</strong> N° ${data.proximo_factura_c}</li>
        </ul>
      `;
      showToast("Conexión con AFIP verificada con éxito.", "success");
    } else {
      body.innerHTML = `
        <div style="color:var(--accent-rose); font-weight:600; margin-bottom:0.5rem;">
          ✕ Error de Conexión AFIP
        </div>
        <p style="font-size:0.875rem; color:var(--text-muted);">${data.error || "Falla al autenticar"}</p>
      `;
      showToast("Falló la conexión con AFIP.", "error");
    }
  } catch (err) {
    body.innerHTML = `<div style="color:var(--accent-rose);">Error de red: ${err.message}</div>`;
  }
}

// ── ASISTENTE CLAVE & CSR ─────────────────────────────────────────────────────

function setupCsrForm() {
  document.getElementById("form-csr").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cuit = document.getElementById("csr-cuit").value.trim();
    const razon = document.getElementById("csr-razon-social").value.trim();
    const bits = parseInt(document.getElementById("csr-bits").value);

    try {
      showToast("Generando clave RSA y archivo CSR...", "info");
      const res = await fetch("/api/config/generar-csr", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cuit, razon_social: razon, bits }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);

      document.getElementById("csr-result-container").classList.remove("hidden");
      document.getElementById("csr-file-path").textContent = data.csr_path;
      document.getElementById("csr-text").value = data.csr_content;

      showToast("CSR y clave privada generados exitosamente.", "success");
    } catch (err) {
      showToast(`Error generando CSR: ${err.message}`, "error");
    }
  });

  document.getElementById("btn-copy-csr").addEventListener("click", () => {
    const text = document.getElementById("csr-text").value;
    navigator.clipboard.writeText(text).then(() => {
      showToast("Contenido del CSR copiado al portapapeles.", "success");
    });
  });
}
