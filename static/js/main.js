/**
 * main.js — Клиентская логика «Фотоархив компании»
 * fetch API для действий: вход, выход, смена роли, блокировка, удаление файла
 */

// =========================================================================
// Вспомогательные функции
// =========================================================================

async function apiFetch(url, options = {}) {
  // Поддержка FormData (login) и JSON
  if (options.json) {
    options.headers = options.headers || {};
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  options.credentials = "same-origin";

  try {
    const resp = await fetch(url, options);
    const data = await resp.json().catch(() => ({}));

    if (!resp.ok) {
      throw { status: resp.status, message: data.error || "Ошибка сервера" };
    }
    return data;
  } catch (err) {
    if (err.message) {
      alert(err.message);
    } else if (typeof err === "object" && err.message) {
      alert(err.message);
    } else {
      alert("Произошла ошибка при выполнении запроса.");
    }
    throw err;
  }
}

// =========================================================================
// Аутентификация
// =========================================================================

document.addEventListener("DOMContentLoaded", () => {
  // Форма входа
  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorDiv = document.getElementById("loginError");
      errorDiv.style.display = "none";
      errorDiv.textContent = "";

      const formData = new FormData(loginForm);
      try {
        const data = await apiFetch("/api/auth/login", {
          method: "POST",
          body: formData,
        });
        // Успешный вход — редирект на поиск
        window.location.href = "/search";
      } catch (err) {
        errorDiv.textContent = err.message || "Ошибка входа";
        errorDiv.style.display = "block";
      }
    });
  }

  // Автоматическое скрытие flash-сообщений
  const messages = document.querySelectorAll(".message");
  messages.forEach((msg) => {
    setTimeout(() => {
      msg.style.transition = "opacity 0.5s";
      msg.style.opacity = "0";
      setTimeout(() => msg.remove(), 500);
    }, 4000);
  });

  // Подтверждение при выборе роли (в таблице пользователей)
  document.querySelectorAll(".role-select").forEach((select) => {
    select.addEventListener("change", async (e) => {
      const userId = e.target.dataset.userId;
      const newRole = e.target.value;
      if (!confirm(`Изменить роль на «${newRole}»?`)) {
        // Вернуть предыдущее значение
        e.target.value = e.target.dataset.prev || e.target.value;
        return;
      }
      try {
        await apiFetch(`/api/admin/users/${userId}/role`, {
          method: "PUT",
          json: { role: newRole },
        });
        e.target.dataset.prev = newRole;
        window.location.reload();
      } catch {
        e.target.value = e.target.dataset.prev || e.target.value;
      }
    });
    // Сохраняем начальное значение
    select.dataset.prev = select.value;
  });

  const fileInput = document.getElementById("fileInput");
  const uploadPreview = document.getElementById("uploadPreview");
  let uploadPreviewUrl = null;

  if (fileInput && uploadPreview) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (uploadPreviewUrl) {
        URL.revokeObjectURL(uploadPreviewUrl);
        uploadPreviewUrl = null;
      }

      if (!file) {
        uploadPreview.className = "preview__page preview__page--empty";
        uploadPreview.innerHTML = "<span>Документ</span><i></i><i></i><i></i><i></i><i></i>";
        return;
      }

      uploadPreviewUrl = URL.createObjectURL(file);
      const fileSize = formatFileSize(file.size);

      if (file.type.startsWith("image/")) {
        uploadPreview.className = "preview__image preview__image--upload";
        uploadPreview.innerHTML = `
          <img src="${uploadPreviewUrl}" alt="">
          <div class="preview__meta">
            <strong>${escapeHtml(file.name)}</strong>
            <small>${fileSize} · ${escapeHtml(file.type || "file")}</small>
          </div>
        `;
        return;
      }

      if (file.type === "application/pdf") {
        uploadPreview.className = "preview__pdf preview__pdf--upload";
        uploadPreview.innerHTML = `
          <iframe class="preview__frame" src="${uploadPreviewUrl}" title="${escapeHtml(file.name)}"></iframe>
          <div class="preview__meta">
            <strong>${escapeHtml(file.name)}</strong>
            <small>${fileSize} · PDF</small>
          </div>
        `;
        return;
      }

      uploadPreview.className = "preview__file";
      uploadPreview.innerHTML = `
        <div class="preview__file-icon">${escapeHtml(getFileExtension(file.name))}</div>
        <div class="preview__meta">
          <strong>${escapeHtml(file.name)}</strong>
          <small>${fileSize} · ${escapeHtml(file.type || "неизвестный тип")}</small>
        </div>
      `;
    });
  }
});

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} байт`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function getFileExtension(fileName) {
  const extension = fileName.split(".").pop();
  return extension && extension !== fileName ? extension.toUpperCase().slice(0, 5) : "FILE";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// =========================================================================
// Выход из системы
// =========================================================================

async function logout() {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  } catch {
    window.location.href = "/login";
  }
}

// =========================================================================
// Удаление файла
// =========================================================================

async function deleteFile(fileId) {
  if (!confirm("Удалить файл из архива? Это действие необратимо.")) return;
  try {
    await apiFetch(`/api/files/delete/${fileId}`, { method: "DELETE" });
    window.location.reload();
  } catch {
    // Ошибка уже показана в apiFetch
  }
}

// =========================================================================
// Блокировка / разблокировка пользователя
// =========================================================================

async function toggleUserStatus(userId, isActive) {
  const action = isActive ? "разблокировать" : "заблокировать";
  if (!confirm(`Вы уверены, что хотите ${action} этого пользователя?`)) return;
  try {
    await apiFetch(`/api/admin/users/${userId}/status`, {
      method: "PUT",
      json: { is_active: isActive },
    });
    window.location.reload();
  } catch {
    // Ошибка уже показана
  }
}
