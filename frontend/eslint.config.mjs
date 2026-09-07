import jsxA11y from 'eslint-plugin-jsx-a11y'
import tsParser from '@typescript-eslint/parser'

/**
 * Accessibility linting.
 *
 * AC-54 requires automated accessibility checks on the Phase 1 screens, and
 * AC-53 requires them completable by keyboard. These rules are errors, not
 * warnings: a warning in a build log is a warning nobody reads, and "usable
 * without a mouse" is a working requirement for staff at a ward desk, not a
 * preference.
 *
 * The plugin is used directly rather than through next/core-web-vitals via
 * FlatCompat, which fails to serialise under ESLint 9.
 */
export default [
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' },
    },
    plugins: { 'jsx-a11y': jsxA11y },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      // Deliberate: focus lands in the field being worked in — the reason for
      // opening the vitals or result-entry form is to type in it.
      'jsx-a11y/no-autofocus': 'off',
    },
  },
]
