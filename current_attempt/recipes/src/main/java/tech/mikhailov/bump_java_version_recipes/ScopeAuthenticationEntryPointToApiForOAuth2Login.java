package tech.mikhailov.bump_java_version_recipes;

import lombok.EqualsAndHashCode;
import lombok.Value;
import org.openrewrite.ExecutionContext;
import org.openrewrite.Option;
import org.openrewrite.Preconditions;
import org.openrewrite.Recipe;
import org.openrewrite.TreeVisitor;
import org.openrewrite.java.JavaIsoVisitor;
import org.openrewrite.java.JavaParser;
import org.openrewrite.java.JavaTemplate;
import org.openrewrite.java.MethodMatcher;
import org.openrewrite.java.search.UsesMethod;
import org.openrewrite.java.tree.J;

/**
 * When a Spring Security 6 HttpSecurity chain configures both
 *   .exceptionHandling(eh -> eh.authenticationEntryPoint(EP))
 * and
 *   .oauth2Login(...)
 * the oauth2Login DSL registers its own LoginUrlAuthenticationEntryPoint that
 * supersedes the global EP for unauthenticated requests (302 redirect to OAuth
 * authorize endpoint). Tests written against the SB-2 contract expect the
 * global EP to fire (401/403). This recipe rewrites
 *   .authenticationEntryPoint(EP)
 * to
 *   .defaultAuthenticationEntryPointFor(EP, new AntPathRequestMatcher(apiPathPattern))
 * so the global EP scope is explicit and survives the oauth2Login DSL.
 *
 * Bailout: the recipe runs only on files where oauth2Login is actually called.
 */
@Value
@EqualsAndHashCode(callSuper = false)
public class ScopeAuthenticationEntryPointToApiForOAuth2Login extends Recipe {

    @Option(displayName = "API path pattern",
            description = "AntPathRequestMatcher pattern that scopes the global entry point. " +
                          "Common values: /api/**, /rest/**, /v1/**.",
            example = "/api/**")
    String apiPathPattern;

    @Override
    public String getDisplayName() {
        return "Scope .authenticationEntryPoint when .oauth2Login is also configured";
    }

    @Override
    public String getDescription() {
        return "Spring Security 6 .oauth2Login() registers a redirect-style entry point " +
               "that supersedes the global .authenticationEntryPoint(EP). Replace the " +
               "global call with .defaultAuthenticationEntryPointFor(EP, " +
               "AntPathRequestMatcher(<api>)) so API requests still receive EP while " +
               "browser flows still get the OAuth redirect.";
    }

    @Override
    public TreeVisitor<?, ExecutionContext> getVisitor() {
        final MethodMatcher targetEp = new MethodMatcher(
            "org.springframework.security.config.annotation.web.configurers.ExceptionHandlingConfigurer authenticationEntryPoint(..)");
        return Preconditions.check(
            new UsesMethod<>("org.springframework.security.config.annotation.web.builders.HttpSecurity oauth2Login(..)"),
            new JavaIsoVisitor<ExecutionContext>() {
                @Override
                public J.MethodInvocation visitMethodInvocation(J.MethodInvocation mi, ExecutionContext ctx) {
                    J.MethodInvocation m = super.visitMethodInvocation(mi, ctx);
                    if (!targetEp.matches(m)) return m;
                    if (m.getSelect() == null || m.getArguments().isEmpty()) return m;

                    JavaTemplate tpl = JavaTemplate.builder(
                            "#{any()}.defaultAuthenticationEntryPointFor(#{any()}, " +
                            "new org.springframework.security.web.util.matcher.AntPathRequestMatcher(\"" + apiPathPattern + "\"))")
                        .build();
                    maybeAddImport("org.springframework.security.web.util.matcher.AntPathRequestMatcher");
                    return tpl.apply(getCursor(),
                            m.getCoordinates().replace(),
                            m.getSelect(),
                            m.getArguments().get(0));
                }
            });
    }
}
