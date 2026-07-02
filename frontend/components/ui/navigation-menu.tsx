// navbar

import * as React from 'react';
import { motion, useScroll, useMotionValueEvent, type Variants } from 'framer-motion';
import { Menu } from 'lucide-react';
import { cn } from '@/lib/utils';

const navItems = [
  { name: 'How it works', href: '#how' },
  { name: 'Benchmark', href: '#benchmark' },
  { name: 'Who it’s for', href: '#who' },
];

const EXPAND_SCROLL_THRESHOLD = 80;

const containerVariants: Variants = {
  expanded: {
    y: 0,
    opacity: 1,
    width: 'auto',
    transition: {
      y: { type: 'spring', damping: 18, stiffness: 250 },
      opacity: { duration: 0.3 },
      type: 'spring',
      damping: 20,
      stiffness: 300,
      staggerChildren: 0.07,
      delayChildren: 0.2,
    },
  },
  collapsed: {
    y: 0,
    opacity: 1,
    width: '3rem',
    transition: {
      type: 'spring',
      damping: 20,
      stiffness: 300,
      when: 'afterChildren',
      staggerChildren: 0.05,
      staggerDirection: -1,
    },
  },
};

const logoVariants: Variants = {
  expanded: { opacity: 1, x: 0, transition: { type: 'spring', damping: 15 } },
  collapsed: { opacity: 0, x: -20, transition: { duration: 0.25 } },
};

const itemVariants: Variants = {
  expanded: { opacity: 1, x: 0, scale: 1, transition: { type: 'spring', damping: 15 } },
  collapsed: { opacity: 0, x: -20, scale: 0.95, transition: { duration: 0.2 } },
};

const collapsedIconVariants: Variants = {
  expanded: { opacity: 0, scale: 0.8, transition: { duration: 0.2 } },
  collapsed: {
    opacity: 1,
    scale: 1,
    transition: { type: 'spring', damping: 15, stiffness: 300, delay: 0.15 },
  },
};

export function AritiqNav() {
  const [isExpanded, setExpanded] = React.useState(true);

  const { scrollY } = useScroll();
  const lastScrollY = React.useRef(0);
  const scrollPositionOnCollapse = React.useRef(0);

  useMotionValueEvent(scrollY, 'change', (latest) => {
    const previous = lastScrollY.current;

    if (isExpanded && latest > previous && latest > 150) {
      setExpanded(false);
      scrollPositionOnCollapse.current = latest;
    } else if (
      !isExpanded &&
      latest < previous &&
      scrollPositionOnCollapse.current - latest > EXPAND_SCROLL_THRESHOLD
    ) {
      setExpanded(true);
    }

    lastScrollY.current = latest;
  });

  const handleNavClick = (e: React.MouseEvent) => {
    if (!isExpanded) {
      e.preventDefault();
      setExpanded(true);
    }
  };

  return (
    <div className="fixed top-4 sm:top-6 left-1/2 -translate-x-1/2 z-50">
      <motion.nav
        initial={{ y: -80, opacity: 0 }}
        animate={isExpanded ? 'expanded' : 'collapsed'}
        variants={containerVariants}
        whileHover={!isExpanded ? { scale: 1.1 } : {}}
        whileTap={!isExpanded ? { scale: 0.95 } : {}}
        onClick={handleNavClick}
        className={cn(
          'relative flex h-12 max-w-[calc(100vw-1rem)] items-center overflow-hidden rounded-full border border-white/60 bg-white/80 shadow-lg backdrop-blur-md',
          !isExpanded && 'cursor-pointer justify-center'
        )}
      >
        <motion.a
          href="/"
          variants={logoVariants}
          onClick={(e) => e.stopPropagation()}
          className="hidden flex-shrink-0 pl-5 pr-2 sm:flex items-center"
        >
          <img src="/logo-icon-dark.png" alt="Aritiq" className="h-6 w-6 object-contain" />
        </motion.a>

        <motion.div
          className={cn(
            'flex items-center gap-0.5 pl-2 pr-1.5 sm:gap-1 sm:pl-0',
            !isExpanded && 'pointer-events-none'
          )}
        >
          {navItems.map((item, i) => (
            <motion.a
              key={item.name}
              href={item.href}
              variants={itemVariants}
              onClick={(e) => e.stopPropagation()}
              className={cn(
                'whitespace-nowrap rounded-full px-2 py-2 text-xs transition-colors sm:px-3 sm:text-sm',
                i === 0
                  ? 'font-semibold text-[#13233d]'
                  : 'font-medium text-[#4a5a72] hover:text-[#13233d]'
              )}
            >
              {item.name}
            </motion.a>
          ))}
          <motion.a
            href="/app"
            variants={itemVariants}
            onClick={(e) => e.stopPropagation()}
            className="ml-1 whitespace-nowrap rounded-full bg-[#13233d] px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-[#1d3352] sm:px-5 sm:py-2.5 sm:text-sm"
          >
            Open App
          </motion.a>
        </motion.div>

        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <motion.div
            variants={collapsedIconVariants}
            animate={isExpanded ? 'expanded' : 'collapsed'}
          >
            <Menu className="h-5 w-5 text-[#13233d]" />
          </motion.div>
        </div>
      </motion.nav>
    </div>
  );
}
