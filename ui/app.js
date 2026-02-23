async function sendMessage() {
  const input = document.getElementById("userInput");
  const chatBox = document.getElementById("chatBox");
  const userText = input.value.trim();
  if (!userText) return;

  const userMessage = document.createElement("div");
  userMessage.className = "user-message";
  userMessage.innerText = userText;
  chatBox.appendChild(userMessage);

  input.value = "";

  const botMessage = document.createElement("div");
  botMessage.className = "bot-message";
  botMessage.innerText = "Thinking...";
  chatBox.appendChild(botMessage);

  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const response = await fetch("https://ads-agent-api-749418005491.us-central1.run.app/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: userText })
    });

    const data = await response.json();
    botMessage.innerText = data.answer || "No response returned.";
  } catch (e) {
    botMessage.innerText = "Error connecting to backend.";
  }

  chatBox.scrollTop = chatBox.scrollHeight;
}
