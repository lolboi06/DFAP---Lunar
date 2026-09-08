const axios = require('axios');

let currentTelemetry = {
    nodes: 8432,
    alerts: 12,
    risk: 'ELEVATED'
};

function generateRealisticThreatEvent() {
    const IPs = ['192.168.1.1', '10.0.0.5', '172.16.254.1', '45.33.32.156', '8.8.8.8', '114.114.114.114', '203.0.113.42', '198.51.100.22'];
    const types = ['DDoS Attempt', 'SQL Injection', 'Unauthorized Access', 'Data Exfiltration', 'Malware Signature', 'Botnet Activity', 'Zero-Day Exploit Attempt'];
    const targets = ['Auth Gateway', 'Database Node-04', 'API Endpoint /v1/users', 'Internal Subnet A', 'Cloud Storage Bucket', 'Load Balancer'];
    return {
        id: 'THRT-' + Math.random().toString(36).substr(2, 6).toUpperCase(),
        timestamp: new Date().toISOString(),
        type: types[Math.floor(Math.random() * types.length)],
        source_ip: IPs[Math.floor(Math.random() * IPs.length)],
        target: targets[Math.floor(Math.random() * targets.length)],
        severity: Math.random() > 0.8 ? 'CRITICAL' : 'WARNING'
    };
}

async function fetchRealOSINTData() {
    try {
        // Fetch real generic data to simulate OSINT from the cloud
        // Using randomuser API to simulate tracked entities
        const response = await axios.get('https://randomuser.me/api/?results=1');
        const user = response.data.results[0];
        const platforms = ['Twitter', 'Telegram', 'DarkWeb', 'Reddit', 'BreachForums'];
        const sentiments = ['Negative', 'Neutral', 'Suspicious', 'Hostile'];
        
        return {
            platform: platforms[Math.floor(Math.random() * platforms.length)],
            user: `@${user.login.username}`,
            location: `${user.location.city}, ${user.location.country}`,
            sentiment: sentiments[Math.floor(Math.random() * sentiments.length)],
            content: `Detected chatter linked to IP subnet in ${user.location.country}. Mentions of recent zero-day vulnerabilities. Investigating further.`,
            confidence: Math.floor(Math.random() * 40) + 60 // 60-99%
        };
    } catch (error) {
        console.error("Cloud API fetch failed:", error.message);
        return null;
    }
}

module.exports = {
    init: (io) => {
        // Telemetry Update Loop (every 5 seconds)
        setInterval(() => {
            currentTelemetry.nodes += Math.floor(Math.random() * 10) - 4; // Fluctuate
            if (currentTelemetry.nodes < 8000) currentTelemetry.nodes = 8000;
            currentTelemetry.alerts = Math.floor(Math.random() * 20);
            currentTelemetry.risk = currentTelemetry.alerts > 15 ? 'CRITICAL' : (currentTelemetry.alerts > 5 ? 'ELEVATED' : 'NORMAL');
            
            io.emit('telemetry_update', currentTelemetry);
        }, 5000);

        // Timeline Threat Event Loop (every 8 seconds)
        setInterval(() => {
            const threat = generateRealisticThreatEvent();
            io.emit('threat_event', threat);
        }, 8000);

        // Real OSINT Fetch Loop (every 12 seconds)
        setInterval(async () => {
            const osint = await fetchRealOSINTData();
            if (osint) {
                io.emit('osint_feed', osint);
            }
        }, 12000);
    },
    getCurrentTelemetry: () => currentTelemetry
};
