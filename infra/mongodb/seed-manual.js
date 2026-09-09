// Destructive PACS reset used by ./reset.sh.
// Do not run from ./start.sh. First-time volumes are seeded by seed.js via Docker init.

db = db.getSiblingDB('pacs');

db.imaging.deleteMany({});

// Seed imaging studies for Patient 1 with EDGE CASES:
// - Exact start time (should be assigned)
// - Exact end time (should be assigned)
// - Just before start (should NOT be assigned - standalone)
// - Just after end (should NOT be assigned - standalone)
// - Middle of parent (should be assigned)
// - Overlapping parents (should go to most recent)
db.imaging.insertMany([
  // Surgery 1: 10:00-12:00 on Jan 15
  // EDGE CASES: exact start, middle, exact end
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-15T10:00:00Z'), // EDGE: Exact start time
    radiologistNote: 'Pre-operative CT scan at surgery start.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'MRI',
    timestamp: new Date('2024-01-15T11:00:00Z'), // Middle
    radiologistNote: 'Intra-operative MRI confirms appendectomy completion.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'X-Ray',
    timestamp: new Date('2024-01-15T12:00:00Z'), // EDGE: Exact end time
    radiologistNote: 'Post-operative X-ray at surgery end.',
    createdAt: new Date()
  },
  // EDGE CASE: Just before Surgery 1 (should NOT be assigned - standalone)
  {
    patientId: 1,
    modality: 'Ultrasound',
    timestamp: new Date('2024-01-15T09:59:00Z'),
    radiologistNote: 'Pre-surgery ultrasound - should be standalone.',
    createdAt: new Date()
  },
  // EDGE CASE: Just after Surgery 1 (should NOT be assigned - standalone)
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-15T12:01:00Z'),
    radiologistNote: 'Post-surgery CT - should be standalone.',
    createdAt: new Date()
  },
  // Emergency Room 1: 14:00-16:00 on Jan 15
  // EDGE CASES: exact start, middle, exact end
  {
    patientId: 1,
    modality: 'X-Ray',
    timestamp: new Date('2024-01-15T14:00:00Z'), // EDGE: Exact start time
    radiologistNote: 'Chest X-ray at ER visit start.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-15T15:00:00Z'), // Middle
    radiologistNote: 'CT scan reveals no abnormalities.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'MRI',
    timestamp: new Date('2024-01-15T16:00:00Z'), // EDGE: Exact end time
    radiologistNote: 'MRI at ER visit end.',
    createdAt: new Date()
  },
  // Surgery 2: 08:00-10:00 on Jan 16
  // EDGE CASES: exact start, middle, exact end
  {
    patientId: 1,
    modality: 'X-Ray',
    timestamp: new Date('2024-01-16T08:00:00Z'), // EDGE: Exact start time
    radiologistNote: 'Pre-operative X-ray for knee replacement at start.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'MRI',
    timestamp: new Date('2024-01-16T09:00:00Z'), // Middle
    radiologistNote: 'Intra-operative MRI confirms knee replacement positioning.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-16T10:00:00Z'), // EDGE: Exact end time
    radiologistNote: 'Post-operative CT at surgery end.',
    createdAt: new Date()
  },
  // Emergency Room 2: 11:00-13:00 on Jan 16 (OVERLAPS with Surgery 2 end at 10:00)
  // EDGE CASES: exact start, middle, exact end
  {
    patientId: 1,
    modality: 'Ultrasound',
    timestamp: new Date('2024-01-16T11:00:00Z'), // EDGE: Exact start time
    radiologistNote: 'Abdominal ultrasound at ER visit start.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'X-Ray',
    timestamp: new Date('2024-01-16T12:00:00Z'), // Middle
    radiologistNote: 'Abdominal X-ray shows no obstruction.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-16T13:00:00Z'), // EDGE: Exact end time
    radiologistNote: 'CT scan at ER visit end.',
    createdAt: new Date()
  },
  // Surgery 3: 09:00-11:00 on Jan 17
  // EDGE CASES: exact start, middle, exact end
  {
    patientId: 1,
    modality: 'CT',
    timestamp: new Date('2024-01-17T09:00:00Z'), // EDGE: Exact start time
    radiologistNote: 'Pre-operative CT at surgery start.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'MRI',
    timestamp: new Date('2024-01-17T10:00:00Z'), // Middle
    radiologistNote: 'Intra-operative MRI during hernia repair.',
    createdAt: new Date()
  },
  {
    patientId: 1,
    modality: 'X-Ray',
    timestamp: new Date('2024-01-17T11:00:00Z'), // EDGE: Exact end time
    radiologistNote: 'Post-operative X-ray at surgery end.',
    createdAt: new Date()
  }
]);

print('Imaging studies seeded successfully!');
print('Total documents:', db.imaging.countDocuments());
