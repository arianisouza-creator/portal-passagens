(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const MIN_JUST = 15;

  const state = {
    modal: "aviao", motivo: "", trecho: "", acomodacao: "",
    bagagem: "Sim", inclui_onibus: "Não", hospedagem: "Não", veiculo: "Não",
  };
  let CIDADES = {};
  let busca = null;                 // resposta de /api/buscar
  let escolha = { ida: null, volta: null };
  let justificativa = "";

  // ------------------------------------------------------------------ utilidades
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const brl = (v) => "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const hora = (s) => (s || "").slice(11, 16);
  const dia = (s) => (s || "").slice(0, 10);
  const dur = (m) => `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`;
  const dataBr = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

  // ------------------------------------------------------------------ botões segmentados
  $$("[data-group]").forEach((seg) => {
    const g = seg.dataset.group;
    const ligado = seg.querySelector("button.on");
    if (ligado) state[g] = ligado.dataset.v;
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b) return;
      seg.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      state[g] = b.dataset.v;
      if (g === "modal") aplicarModal();
      if (g === "trecho") { $("#boxVolta").classList.toggle("hide", state.trecho !== "ida_volta"); invalidarBusca(); }
      atualizarBotao();
    });
  });

  function aplicarModal() {
    const aviao = state.modal === "aviao";
    $("#cardBusca").classList.toggle("hide", !aviao);
    $("#extrasAviao").classList.toggle("hide", !aviao);
    $("#boxOnibusAcom").classList.toggle("hide", aviao);
    invalidarBusca();
  }

  // ------------------------------------------------------------------ cidades
  function popularUF(sel, ufPadrao) {
    sel.innerHTML = Object.keys(CIDADES).sort().map((uf) => `<option value="${uf}">${uf} - ${esc(CIDADES[uf].nome)}</option>`).join("");
    sel.value = ufPadrao;
  }
  function popularCidades(selUf, selCid, cidadePadrao) {
    const lista = CIDADES[selUf.value].cidades;
    selCid.innerHTML = lista.map((c) => `<option>${esc(c.nome)}</option>`).join("");
    if (cidadePadrao && lista.some((c) => c.nome === cidadePadrao)) selCid.value = cidadePadrao;
  }
  const cidadeObj = (uf, nome) => CIDADES[uf].cidades.find((c) => c.nome === nome);

  function atualizarProximos() {
    const c = cidadeObj($("#ufOrigem").value, $("#cidOrigem").value);
    const tem = c && c.proximos;
    $("#boxProximos").classList.toggle("hide", !tem);
    if (tem) $("#proximosRotulo").textContent = c.proximos_rotulo || c.proximos.join(", ");
  }

  fetch("/cotacao/api/cidades").then((r) => r.json()).then((d) => {
    CIDADES = d;
    popularUF($("#ufOrigem"), "PR"); popularCidades($("#ufOrigem"), $("#cidOrigem"), "Londrina");
    popularUF($("#ufDestino"), "SP"); popularCidades($("#ufDestino"), $("#cidDestino"), "São Paulo");
    atualizarProximos();
  });
  $("#ufOrigem").addEventListener("change", () => { popularCidades($("#ufOrigem"), $("#cidOrigem")); atualizarProximos(); invalidarBusca(); });
  $("#cidOrigem").addEventListener("change", () => { atualizarProximos(); invalidarBusca(); });
  $("#ufDestino").addEventListener("change", () => { popularCidades($("#ufDestino"), $("#cidDestino")); invalidarBusca(); });
  $("#cidDestino").addEventListener("change", invalidarBusca);
  $("#chkProximos").addEventListener("change", invalidarBusca);
  $("#dataIda").addEventListener("change", () => {
    $("#dataVolta").min = $("#dataIda").value || $("#dataVolta").min;
    invalidarBusca();
  });
  $("#dataVolta").addEventListener("change", invalidarBusca);

  // máscara de CPF
  $("#cpf").addEventListener("input", (e) => {
    const d = e.target.value.replace(/\D/g, "").slice(0, 11);
    e.target.value = d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  });
  ["nome", "funcao", "obra", "cpf", "rg", "nascimento", "obs"].forEach((id) => $("#" + id).addEventListener("input", atualizarBotao));

  // ------------------------------------------------------------------ busca
  function codigosOrigem() {
    const c = cidadeObj($("#ufOrigem").value, $("#cidOrigem").value);
    let cods = [...c.aeroportos];
    if (c.proximos && $("#chkProximos").checked) cods = cods.concat(c.proximos);
    return cods;
  }
  const codigosDestino = () => [...cidadeObj($("#ufDestino").value, $("#cidDestino").value).aeroportos];

  function invalidarBusca() {
    if (!busca && !escolha.ida) { $("#msgBusca").textContent = ""; return atualizarBotao(); }
    busca = null; escolha = { ida: null, volta: null };
    $("#resultados").innerHTML = ""; $("#avisoPreco").innerHTML = "";
    $("#msgBusca").textContent = "Você mudou os dados da viagem. Busque as opções de novo.";
    atualizarBotao();
  }

  $("#btnBuscar").addEventListener("click", async () => {
    const er = $("#erroBusca"); er.classList.add("hide");
    if (!$("#dataIda").value) return mostrarErroBusca("Informe a data de ida.");
    if (state.trecho === "ida_volta" && !$("#dataVolta").value) return mostrarErroBusca("Informe a data de volta.");
    if (!state.trecho) return mostrarErroBusca("Informe se a viagem é só ida ou ida e volta.");
    const btn = $("#btnBuscar");
    btn.disabled = true; btn.querySelector("span").innerHTML = '<span class="spin"></span> Buscando…';
    $("#msgBusca").textContent = "Consultando voos…";
    try {
      const r = await fetch("/cotacao/api/buscar", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origens: codigosOrigem(), destinos: codigosDestino(),
          data_ida: $("#dataIda").value, data_volta: state.trecho === "ida_volta" ? $("#dataVolta").value : null,
        }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.erro || "Erro na busca.");
      busca = j; escolha = { ida: null, volta: null }; justificativa = "";
      renderResultados();
      if (j.aviso) $("#resultados").insertAdjacentHTML("afterbegin", `<div class="note" style="margin-top:10px">${esc(j.aviso)}</div>`);
      $("#msgBusca").textContent = `${j.cache ? "Resultado recente reaproveitado" : "Busca feita agora"} (${new Date(j.criado_em).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}). Preços direto na companhia; podem mudar até a compra.`;
    } catch (e) {
      mostrarErroBusca(e.message);
      $("#msgBusca").textContent = "";
    } finally {
      btn.disabled = false; btn.querySelector("span").textContent = "Buscar opções";
      atualizarBotao();
    }
  });
  function mostrarErroBusca(t) { const er = $("#erroBusca"); er.textContent = t; er.classList.remove("hide"); }

  function renderOferta(o, trecho, menor) {
    const mesmaData = dia(o.partida) === dia(o.chegada);
    const nums = o.segmentos.map((s) => `${esc(s.cia)} ${esc(s.numero)}`).join(" + ");
    const esc_ = o.escalas === 0 ? "Direto" : `${o.escalas} escala${o.escalas > 1 ? "s" : ""}${o.escalas_em.length ? " (" + esc(o.escalas_em.join(", ")) + ")" : ""}`;
    const melhor = o.preco <= menor + 0.001;
    return `<label class="offer" data-trecho="${trecho}" data-id="${o.id}">
      <input type="radio" name="of_${trecho}" value="${o.id}">
      <div><div class="omain">
        <span class="times">${hora(o.partida)} → ${hora(o.chegada)}${mesmaData ? "" : " <small>(+1)</small>"}</span>
        <span class="chip">${esc(o.origem_id)} → ${esc(o.destino_id)}</span>
        ${melhor ? '<span class="tag ok"><span class="d"></span>Melhor preço</span>' : ""}
        ${o.exemplo ? '<span class="tag warn"><span class="d"></span>Exemplo</span>' : ""}</div>
        <div class="meta">${nums} · ${dur(o.duracao_min)} · ${esc_}${o.tarifa ? " · tarifa " + esc(o.tarifa) : ""}</div></div>
      <div class="price">${brl(o.preco)}<small>na companhia</small></div></label>`;
  }

  function renderExtras(lista, titulo) {
    if (!lista || !lista.length) return "";
    const linhas = lista.map((o) => `<div class="offer" style="cursor:default;opacity:.75;grid-template-columns:1fr auto">
      <div><div class="omain"><span class="times">${hora(o.partida)} → ${hora(o.chegada)}</span><span class="chip">${esc(o.origem_id)} → ${esc(o.destino_id)}</span></div>
      <div class="meta">${o.segmentos.map((s) => esc(s.cia) + " " + esc(s.numero)).join(" + ")} · ${dur(o.duracao_min)} · ${o.escalas === 0 ? "Direto" : o.escalas + " escala(s)"} · ${esc(o.motivo)}</div></div>
      <div class="price">${brl(o.preco_google)}<small>preço Google (agência)</small></div></div>`).join("");
    return `<details style="margin-top:12px"><summary class="note" style="cursor:pointer">${titulo}: ${lista.length} opção(ões) sem preço direto confirmado na companhia (só consulta, não podem ser escolhidas)</summary>${linhas}</details>`;
  }

  function renderResultados() {
    const box = $("#resultados"); box.innerHTML = "";
    const bloco = (titulo, lista, trecho, data) => {
      if (!lista.length) return `<div class="sectitle"><b>${titulo}</b><span>${dataBr(data)}</span></div><div class="note">Nenhum voo encontrado para esse trecho. Tente outra data ou outro aeroporto.</div>`;
      const menor = Math.min(...lista.map((x) => x.preco));
      return `<div class="sectitle"><b>${titulo}</b><span>${dataBr(data)} · ${lista.length} opções, do menor para o maior preço na companhia</span></div>` +
        lista.map((o) => renderOferta(o, trecho, menor)).join("");
    };
    box.innerHTML = bloco("Voo de ida", busca.ida, "ida", $("#dataIda").value) +
      renderExtras(busca.extras && busca.extras.ida, "Ida") +
      (state.trecho === "ida_volta" ? bloco("Voo de volta", busca.volta, "volta", $("#dataVolta").value) + renderExtras(busca.extras && busca.extras.volta, "Volta") : "");
    box.querySelectorAll(".offer").forEach((el) => el.addEventListener("click", () => {
      escolha[el.dataset.trecho] = el.dataset.id;
      box.querySelectorAll(`.offer[data-trecho="${el.dataset.trecho}"]`).forEach((x) => x.classList.toggle("sel", x === el));
      el.querySelector("input").checked = true;
      renderAviso(); atualizarBotao();
    }));
    renderAviso();
  }

  // ------------------------------------------------------------------ melhor preço / justificativa
  function ofertaEscolhida(trecho) { return busca && busca[trecho].find((x) => x.id === escolha[trecho]); }
  function avaliar() {
    // devolve null se faltar escolha; senão {melhorOk, escolhido, melhor}
    if (!busca) return null;
    const trechos = state.trecho === "ida_volta" ? ["ida", "volta"] : ["ida"];
    let escolhido = 0, melhor = 0, ok = true;
    for (const t of trechos) {
      const o = ofertaEscolhida(t);
      if (!o) return null;
      const menor = Math.min(...busca[t].map((x) => x.preco));
      escolhido += o.preco; melhor += menor;
      if (o.preco > menor + 0.001) ok = false;
    }
    return { melhorOk: ok, escolhido, melhor };
  }

  function renderAviso() {
    const el = $("#avisoPreco"); const a = avaliar();
    if (!a) { el.innerHTML = ""; return; }
    if (a.melhorOk) {
      el.innerHTML = `<div class="callout ok"><b>Você escolheu o melhor preço.</b> Total ${brl(a.escolhido)}. Pode solicitar.</div>`;
    } else {
      el.innerHTML = `<div class="callout warn"><b>Esta não é a opção de menor preço.</b> Você escolheu ${brl(a.escolhido)}; o menor total disponível é ${brl(a.melhor)} (diferença de ${brl(a.escolhido - a.melhor)}).<br>
        Para solicitar, explique por que prefere esta opção (horário, aeroporto, bagagem, urgência…).
        <textarea id="justificativa" placeholder="Justificativa obrigatória (mínimo ${MIN_JUST} caracteres)">${esc(justificativa)}</textarea>
        <div class="note" id="contaJust"></div></div>`;
      const ta = $("#justificativa");
      const conta = () => { $("#contaJust").textContent = `${ta.value.trim().length}/${MIN_JUST} caracteres mínimos`; };
      ta.addEventListener("input", () => { justificativa = ta.value; conta(); atualizarBotao(); });
      conta();
    }
  }

  // ------------------------------------------------------------------ validação / envio
  function faltando() {
    const v = (id) => $("#" + id).value.trim();
    if (!v("nome")) return "Preencha o nome do viajante.";
    if (!v("funcao")) return "Preencha a função.";
    if (!v("obra")) return "Preencha a obra.";
    if (v("cpf").replace(/\D/g, "").length !== 11) return "Preencha o CPF (11 dígitos).";
    if (!v("nascimento")) return "Preencha a data de nascimento.";
    if (!state.motivo) return "Escolha o motivo da viagem.";
    if (!state.trecho) return "Escolha ida e volta ou somente ida.";
    if (!v("dataIda")) return "Preencha a data de ida.";
    if (state.trecho === "ida_volta" && !v("dataVolta")) return "Preencha a data de volta.";
    if (state.modal === "onibus") return state.acomodacao ? "" : "Escolha a acomodação no ônibus.";
    if (!busca) return "Clique em “Buscar opções” e escolha um voo.";
    const trechos = state.trecho === "ida_volta" ? ["ida", "volta"] : ["ida"];
    for (const t of trechos) if (!ofertaEscolhida(t)) return `Escolha o voo de ${t}.`;
    const a = avaliar();
    if (a && !a.melhorOk && justificativa.trim().length < MIN_JUST) return "Justifique por que não escolheu o menor preço.";
    return "";
  }
  function atualizarBotao() {
    const f = faltando();
    $("#btnSolicitar").disabled = !!f;
    $("#msgBarra").textContent = f;
  }

  $("#btnSolicitar").addEventListener("click", async () => {
    const er = $("#erroEnvio"); er.classList.add("hide");
    const btn = $("#btnSolicitar"); btn.disabled = true;
    const v = (id) => $("#" + id).value.trim();
    const dados = {
      tipo_solicitacao: v("tipoSolic"), modal: state.modal, internacional: $("#internacional").checked,
      viajante: { nome: v("nome"), funcao: v("funcao"), obra: v("obra"), cpf: v("cpf"), rg: v("rg"), nascimento: v("nascimento") },
      motivo: state.motivo, trecho: state.trecho, data_ida: v("dataIda"), data_volta: state.trecho === "ida_volta" ? v("dataVolta") : null,
      origem: { uf: $("#ufOrigem").value, cidade: $("#cidOrigem").value },
      destino: { uf: $("#ufDestino").value, cidade: $("#cidDestino").value },
      incluir_proximos: state.modal === "aviao" && !$("#boxProximos").classList.contains("hide") && $("#chkProximos").checked,
      acomodacao_onibus: state.acomodacao, bagagem: state.bagagem, inclui_onibus: state.inclui_onibus,
      hospedagem: state.hospedagem, veiculo: state.veiculo, observacoes: v("obs"),
    };
    if (state.modal === "aviao") {
      dados.busca_id = busca.busca_id; dados.escolha_ida = escolha.ida;
      dados.escolha_volta = state.trecho === "ida_volta" ? escolha.volta : null;
      dados.justificativa = justificativa.trim();
    }
    const fd = new FormData();
    fd.append("dados", JSON.stringify(dados));
    const f = $("#documento").files[0]; if (f) fd.append("documento", f);
    try {
      const r = await fetch("/cotacao/api/solicitar", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error((j.erros || ["Erro ao enviar."]).join("\n"));
      $("#form").querySelectorAll(".card, .erro").forEach((c) => c.classList.add("hide"));
      const s = $("#sucesso"); s.classList.remove("hide");
      s.innerHTML = `<div class="chead"><span class="ti2">Solicitação #${j.id} enviada</span></div><p>${j.melhor_preco === 0 ? "Registrada com justificativa de preço." : j.melhor_preco === 1 ? "Você escolheu a opção de menor preço." : "Registrada."}</p>
        <div style="display:flex;gap:8px;margin-top:14px"><button type="button" class="btn btn-blue" onclick="location.reload()">Nova solicitação</button><a class="btn btn-gray" href="/cotacao/solicitacoes${location.search}">Ver solicitações</a></div>`;
      $("#barra").classList.add("hide");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      er.textContent = e.message; er.classList.remove("hide"); atualizarBotao();
    }
  });

  aplicarModal();
  atualizarBotao();
})();
