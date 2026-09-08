const { Server } = require('socket.io');
const cloudDataService = require('../backend/cloudDataService');

module.exports = function(server) {
    const io = new Server(server, {
        cors: { origin: '*' }
    });

    // Initialize the cloud data service with the io instance
    cloudDataService.init(io);

    io.on('connection', (socket) => {
        console.log(`[+] Client connected via Middleware: ${socket.id}`);
        
        // Send immediate current state upon connection
        socket.emit('telemetry_update', cloudDataService.getCurrentTelemetry());
        
        socket.on('disconnect', () => {
            console.log(`[-] Client disconnected via Middleware: ${socket.id}`);
        });
    });
};
