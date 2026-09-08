"""Break-glass policy placeholder (DFAP Stage 3 §27).

**No emergency bypass is implemented, and none may be added here.**

This module exists to state the policy an emergency process would have to meet
and to give future work a named place to attach it. It deliberately contains no
code path that dispatches, authorizes, or relaxes any check. `force_send`,
`skip_authorization` and `ignore_hash` are not parameters anywhere in LDRM; if a
caller passes them they are simply unknown keyword arguments and the call fails.

Any future emergency process must still:
  * identify the acting human,
  * record the reason and the exigency relied upon,
  * cite the applicable legal authority for the emergency provision,
  * create an immutable audit record before the action, not after,
  * be independently reviewed after the fact by someone who did not invoke it.

`AuthorityType.EMERGENCY_PROVISION` already exists in the domain. It changes
which authority is cited on a request; it does not skip review, authorization,
signing, or the dispatch guard. An urgent request follows the same path as a
routine one.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BreakGlassNotImplemented(PermissionError):
    """Raised whenever an emergency bypass is requested."""


#: Parameter names that must never be honoured by any LDRM entry point.
FORBIDDEN_BYPASS_PARAMETERS = frozenset({
    'force_send', 'skip_authorization', 'ignore_hash', 'bypass_guard',
    'skip_review', 'override_policy', 'force_dispatch', 'disable_checks',
})


def reject_bypass_parameters(payload) -> None:
    """Refuse any caller that tries to name a bypass. Called by API schemas."""
    present = sorted(FORBIDDEN_BYPASS_PARAMETERS.intersection(set(payload or ())))
    if present:
        raise BreakGlassNotImplemented(
            'LDRM implements no authorization bypass. Rejected parameters: '
            + ', '.join(present))


class BreakGlassPolicy(ABC):
    """Interface a future, separately reviewed emergency process would implement.

    No concrete implementation is provided or permitted in this stage.
    """

    @abstractmethod
    def request_emergency_access(self, actor_id: str, request_id: str, reason: str,
                                 authority_reference: str) -> Dict[str, Any]:
        """Record an emergency invocation. Must never itself perform a dispatch."""

    @abstractmethod
    def schedule_independent_review(self, invocation_id: str) -> Dict[str, Any]:
        """Queue the mandatory after-the-fact review by an uninvolved reviewer."""


class UnavailableBreakGlassPolicy(BreakGlassPolicy):
    """The only implementation in this stage: it always refuses."""

    def request_emergency_access(self, actor_id, request_id, reason, authority_reference):
        raise BreakGlassNotImplemented(
            'No break-glass workflow is implemented. An urgent request follows the '
            'ordinary path: legal review, recorded human authorization citing the '
            'applicable emergency provision, signing, and the dispatch guard.')

    def schedule_independent_review(self, invocation_id):
        raise BreakGlassNotImplemented('No break-glass workflow is implemented')
