import React from 'react'

interface IconProps {
  size?: number
  color?: string
  className?: string
  strokeWidth?: number
}

const defaults = { size: 20, strokeWidth: 1.75 }

export const RobotIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="3" y="11" width="18" height="10" rx="2" />
    <path d="M12 11V7" />
    <circle cx="12" cy="5" r="2" />
    <path d="M8 15h.01M12 15h.01M16 15h.01" strokeWidth={2.5} />
    <path d="M3 16l-1 1M21 16l1 1" />
  </svg>
)

export const PersonIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="7" r="4" />
    <path d="M4 21c0-4.418 3.582-8 8-8s8 3.582 8 8" />
  </svg>
)

export const CompareIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="2" y="4" width="9" height="16" rx="2" />
    <rect x="13" y="4" width="9" height="16" rx="2" />
    <path d="M7 9h3M7 12h3M7 15h3M14 9h3M14 12h3M14 15h3" />
  </svg>
)

export const GraphIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="5" cy="12" r="2.5" />
    <circle cx="19" cy="6" r="2.5" />
    <circle cx="19" cy="18" r="2.5" />
    <circle cx="12" cy="12" r="2.5" />
    <path d="M7.5 12h2M14.5 12h2M12 9.5v-1.9M17.1 7.3l-2.7 3.2M17.1 16.7l-2.7-3.2" />
  </svg>
)

export const TreeIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M12 3v18" />
    <path d="M12 8l-4 3h8l-4-3z" />
    <path d="M12 13l-5 4h10l-5-4z" />
  </svg>
)

export const ClockIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 3" />
  </svg>
)

export const BookIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M4 19V5a2 2 0 012-2h13a1 1 0 011 1v13" />
    <path d="M4 19a2 2 0 002 2h13a1 1 0 001-1v-1" />
    <path d="M4 19a2 2 0 012-2h13" />
    <path d="M9 7h6M9 11h4" />
  </svg>
)

export const ChevronLeftIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M15 18l-6-6 6-6" />
  </svg>
)

export const ChevronRightIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M9 18l6-6-6-6" />
  </svg>
)

export const WarningIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
    <path d="M12 9v4M12 17h.01" strokeWidth={2} />
  </svg>
)

export const SearchIcon: React.FC<IconProps> = ({ size = 14, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="11" cy="11" r="7" />
    <path d="M21 21l-4.35-4.35" />
  </svg>
)

export const TagIcon: React.FC<IconProps> = ({ size = 14, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z" />
    <circle cx="7" cy="7" r="1.5" fill={color} stroke="none" />
  </svg>
)

export const CalendarIcon: React.FC<IconProps> = ({ size = 14, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="3" y="4" width="18" height="18" rx="2" />
    <path d="M16 2v4M8 2v4M3 10h18" />
  </svg>
)

export const PinIcon: React.FC<IconProps> = ({ size = 14, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M12 2a5 5 0 015 5c0 5-5 13-5 13S7 12 7 7a5 5 0 015-5z" />
    <circle cx="12" cy="7" r="2" />
  </svg>
)

export const LinkIcon: React.FC<IconProps> = ({ size = 14, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
    <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
  </svg>
)

export const PlayIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <polygon points="5,3 19,12 5,21" fill={color} stroke="none" />
  </svg>
)

export const ElderIcon: React.FC<IconProps> = ({ size = 36, color = 'currentColor', className, strokeWidth = 1.5 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="6" r="3.5" />
    <path d="M5 20c0-3.866 3.134-7 7-7s7 3.134 7 7" />
    <path d="M8.5 17c0 0 .8-1.5 2-2" strokeWidth={1} />
    <path d="M9 13.5c-1.5.5-3 1.5-4 3" strokeWidth={1} />
  </svg>
)

export const ClipboardIcon: React.FC<IconProps> = ({ size = 40, color = 'currentColor', className, strokeWidth = 1.5 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <rect x="4" y="4" width="16" height="17" rx="2" />
    <path d="M8 10h8M8 14h6" />
  </svg>
)

export const NodeEmptyIcon: React.FC<IconProps> = ({ size = 32, color = 'currentColor', className, strokeWidth = 1.5 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="9" strokeDasharray="4 2" />
    <path d="M12 8v4M12 16h.01" />
  </svg>
)

export const SendIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className, strokeWidth = defaults.strokeWidth }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}>
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22,2 15,22 11,13 2,9" fill={color} stroke="none" />
  </svg>
)

export const SpinnerIcon: React.FC<IconProps> = ({ size = defaults.size, color = 'currentColor', className }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} style={{ animation: 'spin 1s linear infinite' }}>
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="2" strokeOpacity="0.25" />
    <path d="M12 3a9 9 0 019 9" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
)
