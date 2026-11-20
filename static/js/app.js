/* Сфера — интерфейсные сценарии без внешних зависимостей. */
(function () {
  "use strict";

  var money = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  });

  function ready(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
    } else {
      callback();
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function formatMoney(value) {
    var number = Number(value);
    if (!Number.isFinite(number)) {
      number = 0;
    }
    return money.format(number) + " ₽";
  }

  function csrfToken() {
    var input = document.querySelector("input[name='csrfmiddlewaretoken']");
    if (input) {
      return input.value;
    }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showFlash(message, variant) {
    var area = byId("flash-area");
    if (!area) {
      window.alert(message);
      return;
    }
    var alert = document.createElement("div");
    alert.className = "alert alert-" + (variant || "success") + " alert-dismissible fade show";
    alert.setAttribute("role", "status");
    alert.textContent = message;

    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close";
    close.setAttribute("aria-label", "Закрыть");
    close.addEventListener("click", function () {
      alert.remove();
    });
    alert.appendChild(close);

    area.appendChild(alert);
    window.setTimeout(function () {
      if (alert.isConnected) {
        alert.remove();
      }
    }, 6000);
  }

  function reloadWithFlash(message, variant) {
    try {
      window.sessionStorage.setItem(
        "mb:flash",
        JSON.stringify({ message: message, variant: variant || "success" })
      );
    } catch (error) {
      /* sessionStorage может быть недоступен */
    }
    window.location.reload();
  }

  function restoreFlash() {
    var raw = null;
    try {
      raw = window.sessionStorage.getItem("mb:flash");
      if (raw) {
        window.sessionStorage.removeItem("mb:flash");
      }
    } catch (error) {
      raw = null;
    }
    if (!raw) {
      return;
    }
    try {
      var data = JSON.parse(raw);
      showFlash(data.message, data.variant);
    } catch (error) {
      /* некорректные данные — молча игнорируем */
    }
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-field-error], [data-form-error]").forEach(function (node) {
      node.textContent = "";
    });
    form.querySelectorAll(".is-invalid").forEach(function (node) {
      node.classList.remove("is-invalid");
    });
  }

  function setFormError(form, message) {
    var node = form.querySelector("[data-form-error]");
    if (node) {
      node.textContent = message;
      return;
    }
    showFlash(message, "danger");
  }

  function applyErrors(form, payload) {
    var errors = (payload && payload.errors) || {};
    var shown = false;

    Object.keys(errors).forEach(function (field) {
      var node = form.querySelector('[data-field-error="' + field + '"]');
      if (node) {
        node.textContent = errors[field];
        shown = true;
      }
      form.querySelectorAll('[name="' + field + '"]').forEach(function (input) {
        input.classList.add("is-invalid");
      });
    });

    if (!shown) {
      setFormError(form, (payload && payload.error) || "Не удалось выполнить операцию.");
    }
  }

  function setBusy(form, busy) {
    var submit = form.querySelector("button[type='submit']");
    if (busy) {
      form.dataset.busy = "1";
      if (submit) {
        submit.dataset.originalText = submit.textContent;
        submit.textContent = "Сохраняем…";
        submit.disabled = true;
      }
    } else {
      delete form.dataset.busy;
      if (submit) {
        if (submit.dataset.originalText) {
          submit.textContent = submit.dataset.originalText;
          delete submit.dataset.originalText;
        }
        submit.disabled = false;
      }
    }
  }

  async function postForm(url, form) {
    if (!url || url === "#") {
      throw new Error("Не удалось определить адрес операции. Обновите страницу.");
    }
    var response = await fetch(url, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json"
      },
      body: new FormData(form),
      credentials: "same-origin"
    });

    var payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }

    if (!payload) {
      throw new Error(
        "Сервер вернул неожиданный ответ. Обновите страницу (Ctrl+F5) и попробуйте снова."
      );
    }
    if (!response.ok || payload.ok === false) {
      var failure = new Error(payload.error || "Не удалось выполнить операцию.");
      failure.payload = payload;
      throw failure;
    }
    return payload;
  }

  function hideModal(element) {
    if (element && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(element).hide();
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Модальные окна                                                          */
  /* ---------------------------------------------------------------------- */

  function updateOrderDebt() {
    var total = Number((byId("id_total_amount") || {}).value || 0);
    var paid = Number((byId("id_paid_amount") || {}).value || 0);
    var debt = Math.max(total - paid, 0);
    var node = byId("order-edit-debt");
    if (node) {
      node.textContent = formatMoney(debt);
      node.classList.toggle("is-debt", debt > 0);
    }
  }

  function fillOrderModal(button) {
    var form = byId("order-edit-form");
    if (!form) {
      return;
    }
    form.action = button.getAttribute("data-edit-url") || "";
    clearErrors(form);

    var values = {
      id_client: button.getAttribute("data-client-id"),
      id_service: button.getAttribute("data-service-id"),
      id_stage: button.getAttribute("data-stage-id"),
      id_scheduled_at: button.getAttribute("data-scheduled"),
      id_total_amount: button.getAttribute("data-total"),
      id_paid_amount: button.getAttribute("data-paid"),
      id_payment_method: button.getAttribute("data-payment"),
      id_work_details: button.getAttribute("data-details")
    };

    Object.keys(values).forEach(function (id) {
      var input = byId(id);
      if (!input) {
        return;
      }
      input.value = values[id] || "";
    });

    var lead = byId("order-modal-lead");
    if (lead) {
      lead.textContent =
        "Запись #" + (button.getAttribute("data-order-id") || "") +
        " · " + (button.getAttribute("data-client-name") || "клиент");
    }
    updateOrderDebt();
  }

  function fillPayModal(button) {
    var form = byId("pay-form");
    if (!form) {
      return;
    }
    form.action = button.getAttribute("data-pay-url") || "";
    clearErrors(form);

    var debt = Number(button.getAttribute("data-debt") || 0);
    var label = byId("pay-order-label");
    if (label) {
      label.textContent = button.getAttribute("data-order-label") || "";
    }
    var debtNode = byId("pay-debt-value");
    if (debtNode) {
      debtNode.textContent = formatMoney(debt);
    }

    var amount = byId("id_amount");
    if (amount) {
      amount.value = debt > 0 ? debt.toFixed(2) : "";
      amount.max = debt > 0 ? String(debt) : "";
    }

    var method = button.getAttribute("data-payment") || "cash";
    if (method !== "card") {
      method = "cash";
    }
    form.querySelectorAll('input[name="payment_method"]').forEach(function (radio) {
      radio.checked = radio.value === method;
    });
  }

  function resetServiceModal() {
    var form = byId("service-form");
    if (!form) {
      return;
    }
    form.reset();
    form.action = form.getAttribute("data-action") || form.action;
    var idInput = byId("service-id");
    if (idInput) {
      idInput.value = "";
    }
    var active = byId("id_is_active");
    if (active) {
      active.checked = true;
    }
    var title = byId("service-modal-title");
    if (title) {
      title.textContent = "Новая услуга";
    }
    var submit = byId("service-submit");
    if (submit) {
      submit.textContent = "Добавить услугу";
    }
    clearErrors(form);
  }

  function fillServiceModal(button) {
    var form = byId("service-form");
    if (!form) {
      return;
    }
    clearErrors(form);
    var idInput = byId("service-id");
    if (idInput) {
      idInput.value = button.getAttribute("data-service-id") || "";
    }
    byId("id_name").value = button.getAttribute("data-service-name") || "";
    byId("id_price").value = button.getAttribute("data-service-price") || "";
    byId("id_cost_price").value = button.getAttribute("data-service-cost") || "";
    byId("id_duration_minutes").value = button.getAttribute("data-service-duration") || "60";
    var active = byId("id_is_active");
    if (active) {
      active.checked = button.getAttribute("data-service-active") === "1";
    }
    var title = byId("service-modal-title");
    if (title) {
      title.textContent = "Изменить услугу";
    }
    var submit = byId("service-submit");
    if (submit) {
      submit.textContent = "Сохранить";
    }
  }

  function fillDeleteModal(button) {
    var form = byId("service-delete-form");
    if (!form) {
      return;
    }
    clearErrors(form);
    form.action = button.getAttribute("data-delete-url") || "";
    var name = byId("service-delete-name");
    if (name) {
      name.textContent = button.getAttribute("data-service-name") || "";
    }
  }

  /* ---------------------------------------------------------------------- */
  /* AJAX-формы                                                              */
  /* ---------------------------------------------------------------------- */

  function submitAjax(form) {
    if (form.dataset.busy === "1") {
      return;
    }
    clearErrors(form);
    setBusy(form, true);
    postForm(form.action, form)
      .then(function (payload) {
        reloadWithFlash(payload.message || "Готово.");
      })
      .catch(function (error) {
        applyErrors(form, error.payload || {});
        setBusy(form, false);
      });
  }

  /* ---------------------------------------------------------------------- */
  /* Копирование                                                            */
  /* ---------------------------------------------------------------------- */

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (error) {
        reject(error);
      } finally {
        area.remove();
      }
    });
  }

  /* ---------------------------------------------------------------------- */
  /* Инициализация                                                          */
  /* ---------------------------------------------------------------------- */

  ready(function () {
    restoreFlash();

    if (!window.fetch) {
      showFlash("Браузер не поддерживает fetch — обновите браузер.", "danger");
      return;
    }
    if (!window.bootstrap) {
      showFlash(
        "Bootstrap не загрузился: модальные окна недоступны. Обновите страницу через Ctrl+F5.",
        "danger"
      );
    }

    // Модалка записи.
    var orderModal = byId("orderModal");
    if (orderModal) {
      orderModal.addEventListener("show.bs.modal", function (event) {
        if (event.relatedTarget) {
          fillOrderModal(event.relatedTarget);
        }
      });
      orderModal.addEventListener("shown.bs.modal", function () {
        var first = byId("id_client");
        if (first) {
          first.focus();
        }
      });
    }

    // Модалка оплаты.
    var payModal = byId("payModal");
    if (payModal) {
      payModal.addEventListener("show.bs.modal", function (event) {
        if (event.relatedTarget) {
          fillPayModal(event.relatedTarget);
        }
      });
      payModal.addEventListener("shown.bs.modal", function () {
        var amount = byId("id_amount");
        if (amount) {
          amount.focus();
          amount.select();
        }
      });
    }

    // Модалка услуги.
    var serviceModal = byId("serviceModal");
    if (serviceModal) {
      serviceModal.addEventListener("show.bs.modal", function (event) {
        var button = event.relatedTarget;
        if (button && button.getAttribute("data-service-id")) {
          fillServiceModal(button);
        } else {
          resetServiceModal();
        }
      });
    }

    // Удаление услуги.
    var deleteModal = byId("serviceDeleteModal");
    if (deleteModal) {
      deleteModal.addEventListener("show.bs.modal", function (event) {
        if (event.relatedTarget) {
          fillDeleteModal(event.relatedTarget);
        }
      });
    }

    // Долг в модалке записи.
    ["id_total_amount", "id_paid_amount"].forEach(function (id) {
      var input = byId(id);
      if (input) {
        input.addEventListener("input", updateOrderDebt);
      }
    });

    // Универсальные AJAX-формы.
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM") {
        return;
      }
      if (form.getAttribute("data-ajax-form")) {
        event.preventDefault();
        submitAjax(form);
      }
    });

    // Быстрый перевод по этапам.
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || !form.classList || !form.classList.contains("js-advance")) {
        return;
      }
      event.preventDefault();
      var button = form.querySelector("button[type='submit']");
      if (button) {
        button.disabled = true;
      }
      postForm(form.action, form)
        .then(function (payload) {
          reloadWithFlash(payload.message || "Этап обновлён.");
        })
        .catch(function (error) {
          if (button) {
            button.disabled = false;
          }
          showFlash(error.message, "danger");
        });
    });

    // Переключение «Воронка / Список» без перезагрузки.
    var viewLinks = document.querySelectorAll("[data-view-switch]");
    viewLinks.forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
          return;
        }
        var kanban = byId("kanban-view");
        var list = byId("list-view");
        if (!kanban || !list) {
          return;
        }
        event.preventDefault();
        var mode = link.getAttribute("data-view-switch");
        var showKanban = mode === "kanban";
        kanban.hidden = !showKanban;
        list.hidden = showKanban;

        viewLinks.forEach(function (item) {
          var active = item.getAttribute("data-view-switch") === mode;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-selected", active ? "true" : "false");
        });

        var filters = byId("list-filters");
        if (filters) {
          filters.hidden = showKanban;
        }

        try {
          var url = new URL(window.location.href);
          url.searchParams.set("view", mode);
          if (!url.searchParams.get("filter")) {
            url.searchParams.set("filter", "active");
          }
          window.history.replaceState(null, "", url);
        } catch (error) {
          /* старые браузеры — просто без обновления адреса */
        }
      });
    });

    // Мгновенный поиск по клиентам.
    document.querySelectorAll("[data-instant-search]").forEach(function (input) {
      var table = document.querySelector(input.getAttribute("data-instant-search"));
      if (!table) {
        return;
      }
      var rows = Array.prototype.slice.call(
        table.querySelectorAll(input.getAttribute("data-search-row") || "[data-client-row]")
      );
      if (!rows.length) {
        return;
      }
      var counter = byId("client-search-count");
      var emptyBox = byId("client-search-empty");
      var serverEmpty = table.querySelector(".empty-row");

      var searchForm = input.closest("form");
      if (searchForm) {
        // Список фильтруется на клиенте — не перезагружаем страницу по Enter.
        searchForm.addEventListener("submit", function (event) {
          event.preventDefault();
        });
      }

      input.addEventListener("input", function () {
        var needle = input.value.trim().toLowerCase();

        // Если список пришёл с сервера уже отфильтрованным (?q=…),
        // очистка поля должна вернуть всех клиентов.
        if (!needle) {
          try {
            var current = new URL(window.location.href);
            if (current.searchParams.has("q")) {
              current.searchParams.delete("q");
              window.location.href = current.toString();
              return;
            }
          } catch (error) {
            /* без URL API просто фильтруем доступные строки */
          }
        }

        var visible = 0;

        rows.forEach(function (row) {
          var haystack = (row.getAttribute("data-search") || "").toLowerCase();
          var match = !needle || haystack.indexOf(needle) !== -1;
          row.hidden = !match;
          if (match) {
            visible += 1;
          }
        });

        if (serverEmpty) {
          serverEmpty.hidden = true;
        }
        if (emptyBox) {
          emptyBox.hidden = !(needle && visible === 0);
        }
        if (counter) {
          counter.textContent = needle
            ? "Найдено: " + visible
            : "Найдено: " + rows.length;
        }
      });
    });

    // Копирование текста (напоминания, ссылки).
    document.addEventListener("click", function (event) {
      var button = event.target.closest(".js-copy");
      if (!button) {
        return;
      }
      var text = button.getAttribute("data-copy-text") || "";
      if (!text) {
        return;
      }
      copyText(text)
        .then(function () {
          showFlash("Скопировано в буфер обмена.", "success");
        })
        .catch(function () {
          showFlash("Не удалось скопировать — выделите текст вручную.", "danger");
        });
    });

    // Подстановка цены услуги в сумму новой записи.
    var orderForm = document.querySelector("[data-order-form]");
    if (orderForm) {
      var serviceSelect = orderForm.querySelector(
        orderForm.getAttribute("data-service-select") || "#id_service"
      );
      var totalField = orderForm.querySelector(
        orderForm.getAttribute("data-total-field") || "#id_total_amount"
      );
      if (serviceSelect && totalField) {
        serviceSelect.addEventListener("change", function () {
          var option = serviceSelect.options[serviceSelect.selectedIndex];
          var price = option ? option.getAttribute("data-price") : "";
          if (price !== null && price !== "") {
            totalField.value = Number(price).toFixed(2);
          }
        });
      }
    }

    // Выбор услуги на публичной странице компании.
    var bookingForm = byId("booking-form");
    var bookingService = byId("id_service");
    if (bookingForm && bookingService) {
      var scrollToBooking = function (focusId) {
        var section = byId("booking");
        if (section) {
          section.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        window.setTimeout(function () {
          var field = byId(focusId);
          if (field) {
            field.focus({ preventScroll: true });
          }
        }, 350);
      };

      document.querySelectorAll("[data-book-service]").forEach(function (link) {
        link.addEventListener("click", function (event) {
          event.preventDefault();
          var serviceId = link.getAttribute("data-book-service");
          bookingService.value = serviceId;
          try {
            var url = new URL(window.location.href);
            url.searchParams.set("service", serviceId);
            url.hash = "booking";
            window.history.replaceState(null, "", url);
          } catch (error) {
            /* без URL API форма всё равно уже выбрана */
          }
          scrollToBooking("id_name");
        });
      });

      document.querySelectorAll("[data-book-general]").forEach(function (link) {
        link.addEventListener("click", function (event) {
          event.preventDefault();
          bookingService.value = "";
          try {
            var url = new URL(window.location.href);
            url.searchParams.delete("service");
            url.hash = "booking";
            window.history.replaceState(null, "", url);
          } catch (error) {
            /* игнорируем */
          }
          scrollToBooking("id_service");
        });
      });

      try {
        if (new URL(window.location.href).searchParams.has("service")) {
          scrollToBooking("id_name");
        }
      } catch (error) {
        /* без URL API остаётся обычная якорная навигация */
      }
    }

    // Имя выбранного файла в зоне загрузки.
    document.querySelectorAll(".upload-drop input[type='file']").forEach(function (input) {
      input.addEventListener("change", function () {
        var drop = input.closest(".upload-drop");
        var title = drop ? drop.querySelector(".upload-drop__title") : null;
        if (title && input.files && input.files.length) {
          title.textContent = input.files[0].name;
        }
      });
    });
  });
})();
