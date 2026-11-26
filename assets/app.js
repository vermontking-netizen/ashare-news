(function () {
  "use strict";

  var TZ = "Asia/Shanghai";
  var CAT_LABEL = { flash: "快讯", market: "市场", stock: "个股", ann: "公告", report: "研报" };
  var IMPORTANT_WORDS = [
    "减持", "增持", "回购", "中标", "签约", "订单", "业绩", "预增", "预亏", "扭亏",
    "停牌", "复牌", "立案", "问询", "处罚", "分红", "收购", "重组", "降准", "降息",
    "解禁", "涨停", "跌停", "退市", "澄清", "风险提示", "重大合同", "控制权", "重组",
    "IPO", "增发", "配股", "爆雷", "违约"
  ];
  var PAGE_SIZE = 120;

  var state = {
    cat: "all",
    q: "",
    src: "all",
    todayOnly: false,
    importantOnly: false,
    limit: PAGE_SIZE
  };

  var DATA = null;
  var el = {};

  /* ------------------------------------------------------------ 工具 */

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function safeUrl(url) {
    return /^https?:\/\//i.test(url || "") ? url : "#";
  }

  function dayKey(ts) {
    if (!ts) return "";
    return new Date(ts).toLocaleDateString("sv-SE", { timeZone: TZ });
  }

  function todayKey() {
    return dayKey(new Date().toISOString());
  }

  function clock(ts) {
    if (!ts) return "--:--";
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false
    }).format(new Date(ts));
  }

  function dateTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts);
    var date = new Intl.DateTimeFormat("zh-CN", {
      timeZone: TZ, month: "2-digit", day: "2-digit"
    }).format(d);
    return date + " " + clock(ts);
  }

  function dayLabel(key) {
    if (!key) return "未知日期";
    var today = todayKey();
    var yesterday = dayKey(new Date(Date.now() - 864e5).toISOString());
    var d = new Date(key + "T12:00:00+08:00");
    var dateText = new Intl.DateTimeFormat("zh-CN", {
      timeZone: TZ, month: "long", day: "numeric"
    }).format(d);
    var weekText = new Intl.DateTimeFormat("zh-CN", {
      timeZone: TZ, weekday: "short"
    }).format(d);
    var text = dateText + " " + weekText;
    if (key === today) return "今天 · " + text;
    if (key === yesterday) return "昨天 · " + text;
    return text;
  }

  function relative(ts) {
    if (!ts) return "—";
    var diff = Date.now() - new Date(ts).getTime();
    if (diff < 0) return "刚刚";
    var minutes = Math.floor(diff / 60000);
    if (minutes < 1) return "刚刚";
    if (minutes < 60) return minutes + " 分钟前";
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + " 小时前";
    return Math.floor(hours / 24) + " 天前";
  }

  function isImportant(item) {
    var text = (item.title || "") + " " + (item.tag || "");
    for (var i = 0; i < IMPORTANT_WORDS.length; i++) {
      if (text.indexOf(IMPORTANT_WORDS[i]) !== -1) return true;
    }
    return false;
  }

  function highlight(text) {
    var safe = esc(text);
    var q = state.q.trim();
    if (!q) return safe;
    try {
      var pattern = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      return safe.replace(pattern, "<mark>$1</mark>");
    } catch (err) {
      return safe;
    }
  }

  function toast(message) {
    var node = document.querySelector(".toast");
    if (!node) {
      node = document.createElement("div");
      node.className = "toast";
      document.body.appendChild(node);
    }
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(node._timer);
    node._timer = setTimeout(function () { node.classList.remove("show"); }, 2600);
  }

  /* ------------------------------------------------------------ 筛选 */

  function baseFiltered() {
    var q = state.q.trim().toLowerCase();
    var today = todayKey();
    return DATA.items.filter(function (item) {
      if (state.src !== "all" && item.source !== state.src) return false;
      if (state.todayOnly && dayKey(item.time) !== today) return false;
      if (state.importantOnly && !isImportant(item)) return false;
      if (q) {
        var haystack = [
          item.title, item.summary, item.source, item.tag,
          item.stock ? item.stock.code : "", item.stock ? item.stock.name : ""
        ].join(" ").toLowerCase();
        if (haystack.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  /* ------------------------------------------------------------ 渲染 */

  function renderTabs(base) {
    var counts = { all: base.length };
    ["flash", "market", "stock", "ann", "report"].forEach(function (cat) { counts[cat] = 0; });
    base.forEach(function (item) {
      if (counts[item.cat] != null) counts[item.cat] += 1;
    });
    Object.keys(counts).forEach(function (cat) {
      var node = document.querySelector('[data-count="' + cat + '"]');
      if (node) node.textContent = counts[cat] > 999 ? (counts[cat] / 1000).toFixed(1) + "k" : counts[cat];
    });
  }

  function itemHtml(item) {
    var important = isImportant(item);
    var category = CAT_LABEL[item.cat] || "资讯";
    var stock = item.stock && (item.stock.code || item.stock.name)
      ? '<span class="stock">' + esc((item.stock.code || "") + " " + (item.stock.name || "")) + "</span>"
      : "";
    var tag = item.tag ? '<span class="tag">' + esc(item.tag) + "</span>" : "";
    var url = esc(safeUrl(item.url));
    var timeText = clock(item.time);
    var timeTitle = "";
    if (item.cat === "report" && timeText === "00:00") {
      timeText = "—";
      timeTitle = ' title="研报仅提供发布日期"';
    }
    return (
      '<article class="item cat-' + esc(item.cat) + (important ? " important" : "") + '">' +
        '<div class="time"' + timeTitle + ">" + timeText + "</div>" +
        '<div class="body">' +
          '<div class="meta">' +
            '<span class="badge cat-' + esc(item.cat) + '">' + category + "</span>" +
            '<span class="src">' + esc(item.source) + "</span>" +
            stock + tag +
            (important ? '<span class="badge important-badge">重要</span>' : "") +
          "</div>" +
          '<a class="title" href="' + url + '" target="_blank" rel="noopener noreferrer">' +
            highlight(item.title) + "</a>" +
          (item.summary ? '<p class="summary">' + highlight(item.summary) + "</p>" : "") +
        "</div>" +
        '<a class="go" href="' + url + '" target="_blank" rel="noopener noreferrer">原文 ↗</a>' +
      "</article>"
    );
  }

  function renderFeed(list) {
    var slice = list.slice(0, state.limit);
    var dayTotals = {};
    list.forEach(function (item) {
      var key = dayKey(item.time);
      dayTotals[key] = (dayTotals[key] || 0) + 1;
    });
    var html = "";
    var currentDay = null;
    var buffer = "";

    function flushDay() {
      if (currentDay !== null) {
        html += '<div class="date-head"><span>' + dayLabel(currentDay) +
          '</span><span class="day-count">' + (dayTotals[currentDay] || 0) + " 条</span></div>" + buffer;
      }
    }

    slice.forEach(function (item) {
      var key = dayKey(item.time);
      if (key !== currentDay) {
        flushDay();
        currentDay = key;
        buffer = "";
      }
      buffer += itemHtml(item);
    });
    flushDay();

    el.feed.innerHTML = html || "";
    el.empty.hidden = list.length !== 0;
    el.loadMore.hidden = list.length <= state.limit;
    el.loadMore.textContent = "加载更多（还有 " + Math.max(0, list.length - state.limit) + " 条）";
  }

  function renderSummary(list) {
    var latest = DATA.items.length ? DATA.items[0].time : "";
    var left = '<span>共 <b>' + list.length + "</b> 条" +
      (list.length !== DATA.items.length ? " / 全部 " + DATA.items.length + " 条" : "") +
      (state.q ? "　关键词「" + esc(state.q) + "」" : "") + "</span>";
    var right = "<span>更新于 <b>" + clock(DATA.generated_at) + "</b> · 最新 " +
      relative(latest) + " · " + (DATA.source_ok || 0) + "/" + (DATA.source_total || 0) + " 源正常</span>";
    el.feedSummary.innerHTML = left + right;
  }

  function renderRail() {
    var ok = DATA.source_ok || 0;
    var total = DATA.source_total || 0;
    el.sourceBadge.textContent = ok === total ? total + "/" + total + " 正常" : ok + "/" + total + " 可用";
    el.sourceBadge.classList.toggle("warn", ok !== total);
    el.railUpdated.textContent = dateTime(DATA.generated_at);
    var latest = DATA.items.length ? DATA.items[0].time : "";
    el.railLatest.textContent = relative(latest);
    el.railLatest.title = latest ? new Date(latest).toLocaleString("zh-CN", { timeZone: TZ }) : "";
    el.railNew.textContent = "+" + (DATA.new_count || 0) + " 条";
    el.railTotal.textContent = DATA.items.length + " 条";

    var stale = DATA.generated_at && (Date.now() - new Date(DATA.generated_at).getTime() > 3 * 3600 * 1000);
    el.liveDot.className = "dot" + (ok !== total || stale ? " warn" : "");
    el.updateText.textContent = "更新于 " + dateTime(DATA.generated_at);
    el.updateText.title = "上次抓取的静态快照";
    el.footMeta.textContent = "数据生成 " + dateTime(DATA.generated_at) +
      " · 本次新增 " + (DATA.new_count || 0) + " 条 · 库内 " + DATA.items.length + " 条";

    el.sourceList.innerHTML = (DATA.sources || []).map(function (source) {
      return '<li title="' + esc(source.error || (CAT_LABEL[source.cat] || "")) + '">' +
        '<span class="s-dot' + (source.status === "ok" ? "" : " error") + '"></span>' +
        '<span class="s-name">' + esc(source.name) + "</span>" +
        '<span class="s-count">' + (source.status === "ok" ? source.fetched : "失败") + "</span>" +
      "</li>";
    }).join("");
  }

  function renderSources() {
    var names = [];
    DATA.items.forEach(function (item) {
      if (names.indexOf(item.source) === -1) names.push(item.source);
    });
    names.sort(function (a, b) { return a.localeCompare(b, "zh-CN"); });
    var current = el.sourceSelect.value;
    el.sourceSelect.innerHTML = '<option value="all">全部来源</option>' + names.map(function (name) {
      return '<option value="' + esc(name) + '">' + esc(name) + "</option>";
    }).join("");
    el.sourceSelect.value = names.indexOf(current) !== -1 ? current : "all";
    state.src = el.sourceSelect.value;
  }

  function renderAll() {
    var base = baseFiltered();
    renderTabs(base);
    var list = state.cat === "all" ? base : base.filter(function (item) { return item.cat === state.cat; });
    renderFeed(list);
    renderSummary(list);
  }

  /* ------------------------------------------------------------ 数据加载 */

  function normalize(raw) {
    if (!raw || !Array.isArray(raw.items)) return null;
    raw.items = raw.items.slice().sort(function (a, b) {
      return String(b.time || "").localeCompare(String(a.time || ""));
    });
    return raw;
  }

  function parseNewsJs(text) {
    var start = text.indexOf("{");
    var end = text.lastIndexOf("}");
    if (start < 0 || end <= start) throw new Error("bad data");
    return JSON.parse(text.slice(start, end + 1));
  }

  function fetchLatest() {
    return fetch("data/news.js", { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(parseNewsJs);
  }

  function useData(raw) {
    var data = normalize(raw);
    if (!data) return false;
    DATA = data;
    return true;
  }

  function boot() {
    el = {
      feed: document.getElementById("feed"),
      feedSummary: document.getElementById("feedSummary"),
      empty: document.getElementById("empty"),
      loadMore: document.getElementById("loadMore"),
      tabs: document.getElementById("tabs"),
      toolbar: document.getElementById("toolbar"),
      search: document.getElementById("search"),
      clearSearch: document.getElementById("clearSearch"),
      sourceSelect: document.getElementById("sourceSelect"),
      todayOnly: document.getElementById("todayOnly"),
      importantOnly: document.getElementById("importantOnly"),
      liveDot: document.getElementById("liveDot"),
      updateText: document.getElementById("updateText"),
      sourceBadge: document.getElementById("sourceBadge"),
      railUpdated: document.getElementById("railUpdated"),
      railLatest: document.getElementById("railLatest"),
      railNew: document.getElementById("railNew"),
      railTotal: document.getElementById("railTotal"),
      sourceList: document.getElementById("sourceList"),
      footMeta: document.getElementById("footMeta"),
      refreshBtn: document.getElementById("refreshBtn"),
      aboutBtn: document.getElementById("aboutBtn"),
      aboutModal: document.getElementById("aboutModal"),
      closeAbout: document.getElementById("closeAbout")
    };

    var hash = (location.hash || "").replace("#", "");
    if (CAT_LABEL[hash]) {
      state.cat = hash;
      document.querySelectorAll(".tab").forEach(function (tab) {
        tab.classList.toggle("active", tab.dataset.cat === state.cat);
      });
    }

    if (useData(window.NEWS_DATA)) {
      finishBoot();
    } else {
      fetchLatest()
        .then(function (data) {
          if (!useData(data)) throw new Error("empty");
          finishBoot();
        })
        .catch(function () {
          el.feed.innerHTML = '<div class="empty"><div class="empty-icon">!</div>' +
            "<h3>未找到资讯数据</h3><p>请先运行 <code>python fetch_news.py</code> 生成 data/news.js 后再打开页面。</p></div>";
          el.updateText.textContent = "无数据";
          el.liveDot.className = "dot err";
        });
    }
  }

  function finishBoot() {
    renderSources();
    renderAll();
    renderRail();
    bindEvents();
    syncToolbarHeight();

    if (window.ResizeObserver) {
      new ResizeObserver(syncToolbarHeight).observe(el.toolbar);
    }
    window.addEventListener("resize", syncToolbarHeight);
  }

  function syncToolbarHeight() {
    if (!el.toolbar) return;
    var height = el.toolbar.offsetHeight;
    if (height > 0) {
      document.documentElement.style.setProperty("--toolbar-h", height + "px");
    }
  }

  /* ------------------------------------------------------------ 事件 */

  function bindEvents() {
    el.tabs.addEventListener("click", function (event) {
      var tab = event.target.closest(".tab");
      if (!tab) return;
      state.cat = tab.dataset.cat;
      state.limit = PAGE_SIZE;
      el.tabs.querySelectorAll(".tab").forEach(function (node) {
        node.classList.toggle("active", node === tab);
      });
      if (history.replaceState) {
        history.replaceState(null, "", state.cat === "all" ? location.pathname : "#" + state.cat);
      }
      renderAll();
    });

    var searchTimer = null;
    el.search.addEventListener("input", function () {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.q = el.search.value;
        state.limit = PAGE_SIZE;
        el.clearSearch.hidden = !state.q;
        renderAll();
      }, 120);
    });

    el.clearSearch.addEventListener("click", function () {
      el.search.value = "";
      state.q = "";
      state.limit = PAGE_SIZE;
      el.clearSearch.hidden = true;
      el.search.focus();
      renderAll();
    });

    el.sourceSelect.addEventListener("change", function () {
      state.src = el.sourceSelect.value;
      state.limit = PAGE_SIZE;
      renderAll();
    });

    el.todayOnly.addEventListener("change", function () {
      state.todayOnly = el.todayOnly.checked;
      state.limit = PAGE_SIZE;
      renderAll();
    });

    el.importantOnly.addEventListener("change", function () {
      state.importantOnly = el.importantOnly.checked;
      state.limit = PAGE_SIZE;
      renderAll();
    });

    el.loadMore.addEventListener("click", function () {
      state.limit += PAGE_SIZE;
      renderAll();
    });

    el.refreshBtn.addEventListener("click", function () {
      location.reload();
    });

    function openAbout() {
      el.aboutModal.hidden = false;
      document.body.style.overflow = "hidden";
      el.closeAbout.focus();
    }

    function closeAbout() {
      el.aboutModal.hidden = true;
      document.body.style.overflow = "";
    }

    el.aboutBtn.addEventListener("click", openAbout);
    el.closeAbout.addEventListener("click", closeAbout);
    el.aboutModal.addEventListener("click", function (event) {
      if (event.target.dataset.close) closeAbout();
    });

    document.addEventListener("keydown", function (event) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if (event.key === "/" && !typing) {
        event.preventDefault();
        el.search.focus();
      } else if (event.key === "Escape") {
        if (!el.aboutModal.hidden) {
          closeAbout();
        } else if (document.activeElement === el.search) {
          el.search.value = "";
          state.q = "";
          el.clearSearch.hidden = true;
          el.search.blur();
          renderAll();
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
