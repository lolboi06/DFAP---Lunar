const express = require('express');
const http = require('http');
const cors = require('cors');
const path = require('path');
const setupSockets = require('./middleware/socketHandler');

const app = express();
app.use(cors());

// Serve the DFAP frontend from the frontend directory
app.use(express.static(path.join(__dirname, 'frontend')));

const server = http.createServer(app);

// Setup WebSockets and pass server instance
setupSockets(server);

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`[!] DFAP Backend Server running on http://localhost:${PORT}`);
});
