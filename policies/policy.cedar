permit (
    principal is notification::Service,
    action == Action::"platform-email:send",
    resource
) when {
    resource is notification::PlatformEmailRelay &&
    principal.tokenType == "service" &&
    context.issuer == resource.issuer &&
    resource.allowedSubjects.contains(principal.serviceSlug)
};
