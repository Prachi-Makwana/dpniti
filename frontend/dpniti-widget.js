(function () {
    // Use CONFIG.API_URL from config.js, or fallback to Python service
    const PYTHON_API_URL = typeof CONFIG !== 'undefined' ? (CONFIG.PYTHON_API_URL || 'http://localhost:5001') : 'http://localhost:5001';
    const SESSION_ID = 'dpniti_' + Math.random().toString(36).slice(2);
    const CHAT_STORAGE_KEY = 'dpniti_chat_messages';
    let conversationVersion = 0;

    function formatISTTime(timestamp) {
        return new Intl.DateTimeFormat('en-IN', {
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
            timeZone: 'Asia/Kolkata'
        }).format(new Date(timestamp));
    }

    function createMessage(text, who, timestamp) {
        const msg = document.createElement('div');
        msg.className = 'dpniti-msg ' + who;
        msg.dataset.messageText = text;
        msg.dataset.timestamp = timestamp || new Date().toISOString();

        const content = document.createElement('span');
        content.className = 'dpniti-msg-content';
        content.textContent = text;
        msg.appendChild(content);

        if (!who.includes('typing')) {
            const time = document.createElement('span');
            time.className = 'dpniti-msg-time';
            time.textContent = formatISTTime(msg.dataset.timestamp);
            msg.appendChild(time);
        }

        return msg;
    }

    async function botReply(userText, body) {
    const replyVersion = conversationVersion;
    const typing = createMessage('DPniti is thinking...', 'bot typing');
    body.appendChild(typing);
    body.scrollTop = body.scrollHeight;
    try {
        const res  = await fetch(PYTHON_API_URL + '/chat', {
            method: 'POST',
            credentials: 'include', // sends the httpOnly auth cookie; no token in JS anymore
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                message: userText, 
                session_id: SESSION_ID,
                user_name: localStorage.getItem('userName') || null,
                role: localStorage.getItem('role') || null,
                batch: localStorage.getItem('batch') || null,
                allowed_sem: localStorage.getItem('allowedSem') ? Number(localStorage.getItem('allowedSem')) : null
            })
        });
        const data = await res.json();
        if (replyVersion !== conversationVersion) return;
        typing.remove();
        body.appendChild(createMessage(data.reply, 'bot'));
        saveConversation(body);
    } catch (e) {
        if (replyVersion !== conversationVersion) return;
        typing.remove();
        body.appendChild(createMessage('Could not reach AI server. Make sure chatbot_api.py is running on port 5001.', 'bot'));
        saveConversation(body);
    }
    body.scrollTop = body.scrollHeight;
}

    function saveConversation(body) {
        const messages = Array.from(body.querySelectorAll('.dpniti-msg:not(.typing)')).map(function (message) {
            return {
                text: message.dataset.messageText,
                who: message.classList.contains('user') ? 'user' : 'bot',
                timestamp: message.dataset.timestamp
            };
        });
        localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
    }

    function loadConversation() {
        try {
            const messages = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || '[]');
            return Array.isArray(messages) ? messages : [];
        } catch (e) {
            return [];
        }
    }

    function initWidget() {
        if (document.querySelector('.dpniti-widget-root')) return;

        const root = document.createElement('div');
        root.className = 'dpniti-widget-root';

        const fabWrap = document.createElement('div');
        fabWrap.className = 'dpniti-fab-wrap';

        const prompt = document.createElement('div');
        prompt.className = 'dpniti-prompt';
        prompt.textContent = 'Hii i am DPniti how may i help you ?';

        const fab = document.createElement('button');
        fab.className = 'dpniti-fab';
        fab.setAttribute('aria-label', 'Open DPniti assistant');

        const fabImg = document.createElement('img');
        fabImg.src = 'images/extra/dp.jpeg';
        fabImg.alt = 'DPniti assistant';
        fab.appendChild(fabImg);

        fabWrap.appendChild(prompt);
        fabWrap.appendChild(fab);
        root.appendChild(fabWrap);

        const panel = document.createElement('section');
        panel.className = 'dpniti-chat-panel';

        const header = document.createElement('div');
        header.className = 'dpniti-chat-header';

        const avatar = document.createElement('img');
        avatar.src = 'images/extra/dp.jpeg';
        avatar.className = 'dpniti-header-avatar';
        avatar.alt = 'DPniti';

        const headerInfo = document.createElement('div');
        headerInfo.className = 'dpniti-header-info';

        const title = document.createElement('div');
        title.className = 'dpniti-chat-title';
        title.textContent = 'DPniti';

        const status = document.createElement('div');
        status.className = 'dpniti-header-status';
        status.textContent = '● Online';

        headerInfo.appendChild(title);
        headerInfo.appendChild(status);

        const headerBtns = document.createElement('div');
        headerBtns.className = 'dpniti-header-btns';

        const resetBtn = document.createElement('button');
        resetBtn.className = 'dpniti-reset-btn';
        resetBtn.textContent = '↺';
        resetBtn.title = 'Reset chat';

        const close = document.createElement('button');
        close.className = 'dpniti-minimize';
        close.textContent = '×';
        close.setAttribute('aria-label', 'Minimize chat');

        headerBtns.appendChild(resetBtn);
        headerBtns.appendChild(close);

        header.appendChild(avatar);
        header.appendChild(headerInfo);
        header.appendChild(headerBtns);

        const body = document.createElement('div');
        body.className = 'dpniti-chat-body';
        const savedMessages = loadConversation();
        if (savedMessages.length) {
            savedMessages.forEach(function (message) {
                body.appendChild(createMessage(message.text, message.who, message.timestamp));
            });
        } else {
            body.appendChild(createMessage('Hii i am DPniti! Ask me anything about students, faculty, timetables or subjects.', 'bot'));
            saveConversation(body);
        }

        const disclaimer = document.createElement('div');
        disclaimer.className = 'dpniti-disclaimer';
        disclaimer.textContent = 'DPniti can make mistakes. Check important info.';

        const inputRow = document.createElement('div');
        inputRow.className = 'dpniti-chat-input';

        const input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'Type your message...';

        const send = document.createElement('button');
        send.type = 'button';
        send.className = 'dpniti-send-btn';
        send.innerHTML = '<span aria-hidden="true">&#10148;</span>';
        send.setAttribute('aria-label', 'Send message');

        inputRow.appendChild(input);
        inputRow.appendChild(send);

        panel.appendChild(header);
        panel.appendChild(body);
        panel.appendChild(disclaimer);
        panel.appendChild(inputRow);

        root.appendChild(panel);
        document.body.appendChild(root);

        function openPanel() {
            panel.classList.add('open');
            fabWrap.style.display = 'none';
            input.focus();
        }

        function closePanel() {
            panel.classList.remove('open');
            fabWrap.style.display = 'flex';
        }

        function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            body.appendChild(createMessage(text, 'user'));
            input.value = '';
            body.scrollTop = body.scrollHeight;
            saveConversation(body);
            botReply(text, body);
        }

        resetBtn.addEventListener('click', async function () {
                conversationVersion += 1;
            await fetch(PYTHON_API_URL + '/reset', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: SESSION_ID })
            }).catch(() => {});
            body.innerHTML = '';
            body.appendChild(createMessage('Chat reset! How can I help you?', 'bot'));
            saveConversation(body);
        });

        fab.addEventListener('click', openPanel);
        prompt.addEventListener('click', openPanel);
        close.addEventListener('click', closePanel);
        send.addEventListener('click', sendMessage);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') sendMessage();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWidget);
    } else {
        initWidget();
    }
})();