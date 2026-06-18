import {
  BarChart3,
  Database,
  Info,
  MonitorCog,
  RadioTower,
  Share2,
  ShieldAlert,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react';

export type SettingsSection =
  | 'radio'
  | 'local'
  | 'radio-app'
  | 'spam-defense'
  | 'database'
  | 'fanout'
  | 'statistics'
  | 'about';

export const SETTINGS_SECTION_ORDER: SettingsSection[] = [
  'radio',
  'local',
  'fanout',
  'radio-app',
  'spam-defense',
  'database',
  'statistics',
  'about',
];

export const SETTINGS_SECTION_LABELS: Record<SettingsSection, string> = {
  radio: 'Radio',
  local: 'Local Configuration',
  'radio-app': 'Radio-App Management',
  'spam-defense': 'Spam Defense',
  database: 'Database',
  fanout: 'MQTT & Automation',
  statistics: 'Statistics',
  about: 'About',
};

export const SETTINGS_SECTION_ICONS: Record<SettingsSection, LucideIcon> = {
  radio: RadioTower,
  local: MonitorCog,
  'radio-app': SlidersHorizontal,
  'spam-defense': ShieldAlert,
  database: Database,
  fanout: Share2,
  statistics: BarChart3,
  about: Info,
};
