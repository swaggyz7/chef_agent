const messagesEl = document.querySelector("#messages");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const imageInput = document.querySelector("#imageInput");
const sendButton = document.querySelector("#sendButton");
const clearButton = document.querySelector("#clearButton");
const uploadPreview = document.querySelector("#uploadPreview");
const previewImage = document.querySelector("#previewImage");
const previewName = document.querySelector("#previewName");
const removeImageButton = document.querySelector("#removeImage");
const modelStatus = document.querySelector("#modelStatus");
const ossStatus = document.querySelector("#ossStatus");

let selectedFile = null;
let selectedPreviewUrl = "";
let isSending = false;

const storageKey = "chef-thread-id";
const threadId =
  localStorage.getItem(storageKey) ||
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

localStorage.setItem(storageKey, threadId);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInline(value) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  return text;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replaceAll("\r\n", "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";

  const closeParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = "";
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      closeParagraph();
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeParagraph();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      closeParagraph();
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${renderInline(unordered[1])}</li>`);
      continue;
    }

    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      closeParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${renderInline(ordered[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }

  closeParagraph();
  closeList();
  return html.join("");
}

function absoluteUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url) || url.startsWith("data:")) return url;
  return new URL(url, window.location.origin).href;
}

function addMessage(role, content, imageUrl, typing = false) {
  const article = document.createElement("article");
  article.className = `message ${role}${typing ? " typing" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "assistant" ? "厨" : "我";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (imageUrl) {
    const image = document.createElement("img");
    image.className = "message-image";
    image.src = absoluteUrl(imageUrl);
    image.alt = "用户上传的食材";
    bubble.appendChild(image);
  }

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = renderMarkdown(content);
  bubble.appendChild(body);

  article.append(avatar, bubble);
  messagesEl.appendChild(article);
  scrollToBottom();
  return { article, bubble, body };
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });
}

function setStatus(element, configured, okText, warnText) {
  element.textContent = configured ? okText : warnText;
  element.className = `status-dot ${configured ? "ok" : "warn"}`;
}

async function loadRuntimeStatus() {
  setStatus(modelStatus, false, "已连接", "未配置");
  setStatus(ossStatus, false, "OSS 已连接", "本地上传");
  try {
    const response = await fetch("/api/v1/status");
    const data = await response.json();
    setStatus(modelStatus, data.dashscope_configured, "已连接", "未配置");
    setStatus(ossStatus, data.oss_configured, "OSS 已连接", "本地上传");
  } catch (error) {
    console.error("读取运行状态失败", error);
  }
}

async function loadHistory() {
  try {
    const response = await fetch(
      `/api/v1/chat/messages?thread_id=${encodeURIComponent(threadId)}`,
    );
    if (!response.ok) return;
    const data = await response.json();
    if (!data.messages?.length) return;

    messagesEl.innerHTML = "";
    for (const message of data.messages) {
      addMessage(message.role, message.content, message.image_url);
    }
  } catch (error) {
    console.error("加载历史消息失败", error);
  }
}

function clearSelectedImage() {
  if (selectedPreviewUrl) {
    URL.revokeObjectURL(selectedPreviewUrl);
  }
  selectedFile = null;
  selectedPreviewUrl = "";
  imageInput.value = "";
  uploadPreview.hidden = true;
  previewImage.removeAttribute("src");
}

function prepareImage(file) {
  if (!file) return;
  clearSelectedImage();
  selectedFile = file;
  selectedPreviewUrl = URL.createObjectURL(file);
  previewImage.src = selectedPreviewUrl;
  previewName.textContent = file.name;
  uploadPreview.hidden = false;
}

async function uploadImage(file) {
  const statusResponse = await fetch("/api/v1/oss/status");
  const status = await statusResponse.json();

  if (status.configured) {
    const presignResponse = await fetch("/api/v1/oss/presign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "image/jpeg",
      }),
    });
    const presign = await presignResponse.json();
    if (!presignResponse.ok) {
      throw new Error(presign.detail || "获取 OSS 上传签名失败");
    }

    const uploadResponse = await fetch(presign.upload_url, {
      method: presign.method || "PUT",
      headers: presign.headers || { "Content-Type": file.type || "image/jpeg" },
      body: file,
    });
    if (!uploadResponse.ok) {
      throw new Error("图片上传到 OSS 失败，请检查 Bucket 权限和跨域配置");
    }
    return absoluteUrl(presign.file_url);
  }

  const formData = new FormData();
  formData.append("file", file);
  const localResponse = await fetch("/api/v1/oss/local-upload", {
    method: "POST",
    body: formData,
  });
  const localResult = await localResponse.json();
  if (!localResponse.ok) {
    throw new Error(localResult.detail || "本地图片上传失败");
  }
  return absoluteUrl(localResult.file_url);
}

function setSending(value) {
  isSending = value;
  sendButton.disabled = value;
  messageInput.disabled = value;
  imageInput.disabled = value;
}

async function streamAnswer(text, imageUrl, assistantBody, assistantArticle) {
  const response = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      image_url: imageUrl || null,
      thread_id: threadId,
    }),
  });

  if (!response.ok || !response.body) {
    const detail = await response.text();
    throw new Error(detail || "聊天接口请求失败");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let answer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    answer += decoder.decode(value, { stream: true });
    assistantBody.innerHTML = renderMarkdown(answer);
    scrollToBottom();
  }

  answer += decoder.decode();
  assistantBody.innerHTML = renderMarkdown(answer || "暂时没有生成有效回答，请稍后重试。");
  assistantArticle.classList.remove("typing");
  if (answer.includes("尚未配置") || answer.includes("信息检索失败")) {
    assistantBody.classList.add("error-text");
  }
  return answer;
}

async function sendMessage(explicitText = "") {
  if (isSending) return;

  const text = (explicitText || messageInput.value).trim();
  if (!text && !selectedFile) return;

  const fileToUpload = selectedFile;
  const localPreview = selectedPreviewUrl;
  const displayText = text || "请识别这张食材照片，并推荐适合的菜谱。";

  addMessage("user", displayText, localPreview);
  messageInput.value = "";
  autoResize();
  clearSelectedImage();
  setSending(true);

  const assistant = addMessage("assistant", "", null, true);
  try {
    const imageUrl = fileToUpload ? await uploadImage(fileToUpload) : null;
    await streamAnswer(displayText, imageUrl, assistant.body, assistant.article);
  } catch (error) {
    console.error(error);
    assistant.article.classList.remove("typing");
    assistant.body.classList.add("error-text");
    assistant.body.innerHTML = renderMarkdown(`请求失败：${error.message}`);
  } finally {
    setSending(false);
    messageInput.focus();
    scrollToBottom();
  }
}

function autoResize() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 150)}px`;
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

messageInput.addEventListener("input", autoResize);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

imageInput.addEventListener("change", () => {
  prepareImage(imageInput.files?.[0]);
});

removeImageButton.addEventListener("click", clearSelectedImage);

document.addEventListener("click", (event) => {
  const promptButton = event.target.closest("[data-prompt]");
  if (!promptButton) return;
  messageInput.value = promptButton.dataset.prompt || "";
  autoResize();
  messageInput.focus();
});

clearButton.addEventListener("click", async () => {
  if (isSending) return;
  const confirmed = window.confirm("确定清空当前会话吗？");
  if (!confirmed) return;

  try {
    await fetch(`/api/v1/chat/messages?thread_id=${encodeURIComponent(threadId)}`, {
      method: "DELETE",
    });
    messagesEl.innerHTML = "";
    addMessage("assistant", "会话已清空。把新的食材照片或清单发给我吧。");
  } catch (error) {
    console.error("清空会话失败", error);
  }
});

loadRuntimeStatus();
loadHistory();
autoResize();