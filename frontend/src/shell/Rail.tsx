/**
 * The navigation rail — pinned open at 208px, showing an icon, a name and a
 * task-count badge per destination.
 *
 * Below 1024px the width is worth more to the screen than to the navigation, so
 * there it collapses to a 56px icon rail and expands over the content on hover
 * or keyboard focus. Both states are the same markup; only CSS differs, so the
 * abbreviated wordmark is in the DOM at every width.
 *
 * Badges show outstanding work. They are empty in Stage 0 because there is no
 * work yet; the counts arrive with the outstanding-tasks service at Stage 5,
 * and the shape is here so that adding them is a data change rather than a
 * layout change.
 */

import { NavLink } from 'react-router-dom'

import { useTaskCounts } from '@/lib/dashboard'

import { icons } from './icons'
import { DESTINATIONS, SETTINGS_DESTINATION, type Destination } from './navigation'

interface RailItemProps {
  readonly destination: Destination
  /** `exactOptionalPropertyTypes` is on, so absent and undefined are distinct. */
  readonly badge?: number | undefined
}

function RailItem({ destination, badge }: RailItemProps) {
  return (
    <NavLink
      to={destination.path}
      end={destination.path === '/'}
      className={({ isActive }) => `rail__item${isActive ? ' rail__item--active' : ''}`}
      title={destination.label}
    >
      <span className="rail__icon">{icons[destination.icon]}</span>
      <span className="rail__label">{destination.label}</span>
      {badge !== undefined && badge > 0 && <span className="rail__badge mono">{badge}</span>}
    </NavLink>
  )
}

export function Rail() {
  // Badges show outstanding work, from the same service the dashboard's
  // conscience panel uses. One definition, two renderings.
  const counts = useTaskCounts()

  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail__mark">
        <span className="rail__mark--full">Financial Hub</span>
        <span className="rail__mark--short">FH</span>
      </div>

      <div className="rail__group">
        {DESTINATIONS.map((destination) => (
          <RailItem
            key={destination.path}
            destination={destination}
            badge={counts.data?.[destination.path]}
          />
        ))}
      </div>

      {/* Pinned to the bottom, separated from the tab group. */}
      <div className="rail__foot">
        <RailItem destination={SETTINGS_DESTINATION} />
      </div>
    </nav>
  )
}
