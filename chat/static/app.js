/**
 * Engineering Knowledge Graph - Chat Application
 */

class EKGChat {
    constructor() {
        this.messagesContainer = document.getElementById('messages');
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.clearBtn = document.getElementById('clearBtn');
        this.suggestions = document.getElementById('suggestions');
        this.statusDot = document.getElementById('statusDot');
        this.statusText = document.getElementById('statusText');

        // Graph elements
        this.graphBtn = document.getElementById('graphBtn');
        this.graphModal = document.getElementById('graphModal');
        this.closeGraphBtn = document.getElementById('closeGraphBtn');
        this.resetLayoutBtn = document.getElementById('resetLayoutBtn');
        this.cy = null;

        this.isLoading = false;

        this.init();
    }

    init() {
        // Load session ID
        this.sessionId = localStorage.getItem('ekg_session_id');

        // Event listeners
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.clearBtn.addEventListener('click', () => this.clearChat());
        this.graphBtn.addEventListener('click', () => this.openGraph());
        this.closeGraphBtn.addEventListener('click', () => this.closeGraph());
        this.resetLayoutBtn.addEventListener('click', () => this.resetLayout());

        // Close modal when clicking outside
        window.addEventListener('click', (e) => {
            if (e.target === this.graphModal) {
                this.closeGraph();
            }
        });

        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Auto-resize textarea
        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 200) + 'px';
        });

        // Suggestion clicks
        this.suggestions.querySelectorAll('.suggestion').forEach(btn => {
            btn.addEventListener('click', () => {
                this.messageInput.value = btn.dataset.query;
                this.sendMessage();
            });
        });

        // Check health on load
        this.checkHealth();
    }

    async checkHealth() {
        try {
            const response = await fetch('/health');
            const data = await response.json();

            if (data.status === 'healthy') {
                this.setStatus('connected', `${data.node_count} nodes`);
            } else {
                this.setStatus('error', 'Disconnected');
            }
        } catch (error) {
            this.setStatus('error', 'Disconnected');
        }
    }

    setStatus(status, text) {
        this.statusDot.className = 'status-dot';
        if (status === 'connected') {
            this.statusDot.classList.add('connected');
        } else if (status === 'error') {
            this.statusDot.classList.add('error');
        }
        this.statusText.textContent = text;
    }

    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message || this.isLoading) return;

        // Add user message
        this.addMessage(message, 'user');
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        // Show loading
        this.isLoading = true;
        this.sendBtn.disabled = true;
        const loadingId = this.addLoadingMessage();

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message,
                    session_id: this.sessionId
                }),
            });

            const data = await response.json();

            // Store new session ID if provided
            if (data.session_id) {
                this.sessionId = data.session_id;
                localStorage.setItem('ekg_session_id', this.sessionId);
            }

            // Remove loading
            this.removeMessage(loadingId);

            // Add response
            this.addMessage(data.response, 'assistant');

        } catch (error) {
            this.removeMessage(loadingId);
            this.addMessage('Sorry, there was an error processing your request. Please try again.', 'assistant');
        } finally {
            this.isLoading = false;
            this.sendBtn.disabled = false;
            this.messageInput.focus();
        }
    }

    addMessage(text, role) {
        const messageId = `msg-${Date.now()}`;
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        messageDiv.id = messageId;

        const avatar = role === 'user' ? '👤' : '🤖';

        messageDiv.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-text">${this.formatMessage(text)}</div>
            </div>
        `;

        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();

        return messageId;
    }

    addLoadingMessage() {
        const messageId = `loading-${Date.now()}`;
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant loading';
        messageDiv.id = messageId;

        messageDiv.innerHTML = `
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                <div class="message-text">
                    <div class="typing-indicator">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                </div>
            </div>
        `;

        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();

        return messageId;
    }

    removeMessage(messageId) {
        const message = document.getElementById(messageId);
        if (message) {
            message.remove();
        }
    }

    formatMessage(text) {
        if (!text) return '';

        // Convert markdown-like formatting
        let formatted = text
            // Code blocks
            .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // Bold
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*([^*]+)\*/g, '<em>$1</em>')
            // Line breaks
            .replace(/\n/g, '<br>');

        // Handle lists
        formatted = formatted.replace(/(^|\<br\>)- (.+?)(?=\<br\>|$)/g, '$1<li>$2</li>');
        formatted = formatted.replace(/(<li>.*<\/li>)+/g, '<ul>$&</ul>');

        return formatted;
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    async clearChat() {
        // Keep only the welcome message
        const messages = this.messagesContainer.querySelectorAll('.message');
        messages.forEach((msg, index) => {
            if (index > 0) {
                msg.remove();
            }
        });

        // Clear context on server
        if (this.sessionId) {
            try {
                await fetch('/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: '',
                        clear_context: true,
                        session_id: this.sessionId
                    }),
                });
            } catch (error) {
                console.error('Failed to clear context:', error);
            }
        }

        this.messageInput.focus();
    }

    async openGraph() {
        this.graphModal.style.display = 'block';

        // Initialize or refresh graph
        if (!this.cy) {
            await this.renderGraph();
        } else {
            this.cy.resize();
            this.cy.layout({ name: 'cose', animate: true }).run();
        }
    }

    closeGraph() {
        this.graphModal.style.display = 'none';
    }

    resetLayout() {
        if (this.cy) {
            this.cy.layout({
                name: 'cose',
                animate: true,
                randomize: false,
                componentSpacing: 100,
                nodeOverlap: 20,
                idealEdgeLength: 100,
                edgeElasticity: 100
            }).run();
        }
    }

    async fetchGraphData() {
        try {
            const [nodesRes, edgesRes] = await Promise.all([
                fetch('/graph/nodes'),
                fetch('/graph/edges')
            ]);

            const nodes = await nodesRes.json();
            const edges = await edgesRes.json();

            return { nodes, edges };
        } catch (error) {
            console.error('Failed to fetch graph data:', error);
            return { nodes: [], edges: [] };
        }
    }

    async renderGraph() {
        const data = await this.fetchGraphData();

        // Transform data for Cytoscape
        const elements = [
            ...data.nodes.map(node => ({
                data: {
                    id: node.id,
                    label: node.name || node.id,
                    type: node.type
                },
                classes: node.type.toLowerCase()
            })),
            ...data.edges.map(edge => ({
                data: {
                    id: edge.id || `${edge.source}-${edge.target}`,
                    source: edge.source,
                    target: edge.target,
                    label: edge.type
                }
            }))
        ];

        this.cy = cytoscape({
            container: document.getElementById('cy'),
            elements: elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': '#666',
                        'label': 'data(label)',
                        'color': '#fff',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'text-outline-width': 2,
                        'text-outline-color': '#555',
                        'width': 40,
                        'height': 40,
                        'font-size': '12px'
                    }
                },
                {
                    selector: 'node.service',
                    style: {
                        'background-color': '#58a6ff',
                        'text-outline-color': '#58a6ff'
                    }
                },
                {
                    selector: 'node.database',
                    style: {
                        'background-color': '#3fb950',
                        'text-outline-color': '#3fb950'
                    }
                },
                {
                    selector: 'node.team',
                    style: {
                        'background-color': '#d29922',
                        'text-outline-color': '#d29922'
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 2,
                        'line-color': '#30363d',
                        'target-arrow-color': '#30363d',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier',
                        'label': 'data(label)',
                        'font-size': '10px',
                        'color': '#8b949e',
                        'text-rotation': 'autorotate',
                        'text-background-opacity': 1,
                        'text-background-color': '#0d1117',
                        'text-background-padding': '3px'
                    }
                }
            ],
            layout: {
                name: 'cose',
                idealEdgeLength: 100,
                nodeOverlap: 20,
                refresh: 20,
                fit: true,
                padding: 30,
                randomize: false,
                componentSpacing: 100,
                nodeRepulsion: 400000,
                edgeElasticity: 100,
                nestingFactor: 5,
                gravity: 80,
                numIter: 1000,
                initialTemp: 200,
                coolingFactor: 0.95,
                minTemp: 1.0
            }
        });
    }
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    new EKGChat();
});
