const express = require('express');
const cors = require('cors');

const app = express();
const PORT = 5000;

app.use(cors());
app.use(express.json());

// Stocare în memorie pentru energia activă totală (kWh), incrementată la fiecare apel
let totalActiveEnergy = 1000.0;

// Funcție ajutătoare pentru generarea unei valori aleatoare în jurul unei valori de bază
function randomAround(base, variation) {
  return Number((base + (Math.random() * 2 - 1) * variation).toFixed(2));
}

app.get('/api/energy-data', (req, res) => {
  // Incrementăm energia activă totală la fiecare apel (ex: între 0.05 și 0.25 kWh)
  const increment = Number((0.05 + Math.random() * 0.2).toFixed(3));
  totalActiveEnergy = Number((totalActiveEnergy + increment).toFixed(3));

  const data = {
    timestamp: new Date().toISOString(),
    currents: {
      L1: randomAround(15, 0.8),
      L2: randomAround(15, 0.8),
      L3: randomAround(15, 0.8),
      unit: 'A'
    },
    phaseVoltages: {
      L1_N: randomAround(230, 3.0),
      L2_N: randomAround(230, 3.0),
      L3_N: randomAround(230, 3.0),
      unit: 'V'
    },
    lineVoltages: {
      L1_L2: randomAround(400, 5.0),
      L2_L3: randomAround(400, 5.0),
      L3_L1: randomAround(400, 5.0),
      unit: 'V'
    },
    totalActiveEnergy: {
      value: totalActiveEnergy,
      unit: 'kWh'
    }
  };

  res.json(data);
});

app.listen(PORT, () => {
  console.log(`Serverul rulează pe http://localhost:${PORT}`);
});
