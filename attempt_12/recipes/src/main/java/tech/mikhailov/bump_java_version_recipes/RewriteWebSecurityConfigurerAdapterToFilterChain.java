package tech.mikhailov.bump_java_version_recipes;

import lombok.EqualsAndHashCode;
import lombok.Value;
import org.openrewrite.ExecutionContext;
import org.openrewrite.Preconditions;
import org.openrewrite.Recipe;
import org.openrewrite.TreeVisitor;
import org.openrewrite.java.JavaIsoVisitor;
import org.openrewrite.java.JavaTemplate;
import org.openrewrite.java.search.UsesType;
import org.openrewrite.java.tree.J;
import org.openrewrite.java.tree.JavaType;
import org.openrewrite.java.tree.TypeTree;
import org.openrewrite.java.tree.TypeUtils;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * MVP: remove `extends WebSecurityConfigurerAdapter`, transform the
 * `configure(HttpSecurity)` method into the @Bean SecurityFilterChain pattern,
 * delete any `authenticationManagerBean()` override that just delegates to
 * `super`. Auth manager bean exposure (BeanIds.AUTHENTICATION_MANAGER) is lost
 * — the operator can re-add it via a manual AuthenticationConfiguration-based
 * @Bean if needed.
 */
@Value
@EqualsAndHashCode(callSuper = false)
public class RewriteWebSecurityConfigurerAdapterToFilterChain extends Recipe {

    private static final String WSCA_FQN =
            "org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter";
    private static final String HTTP_SECURITY_FQN =
            "org.springframework.security.config.annotation.web.builders.HttpSecurity";
    private static final String SECURITY_FILTER_CHAIN_FQN =
            "org.springframework.security.web.SecurityFilterChain";
    private static final String BEAN_FQN =
            "org.springframework.context.annotation.Bean";

    @Override public String getDisplayName() {
        return "Convert WebSecurityConfigurerAdapter classes to SecurityFilterChain beans (MVP)";
    }

    @Override public String getDescription() {
        return "Remove `extends WebSecurityConfigurerAdapter`, convert " +
               "`configure(HttpSecurity)` to `@Bean SecurityFilterChain`, " +
               "drop any `authenticationManagerBean()` override that delegates " +
               "to super. Spring Security 6 / Spring Boot 3 compatible.";
    }

    @Override public TreeVisitor<?, ExecutionContext> getVisitor() {
        return Preconditions.check(new UsesType<>(WSCA_FQN, true), new JavaIsoVisitor<ExecutionContext>() {

            final ThreadLocal<Boolean> classExtendsWsca = ThreadLocal.withInitial(() -> Boolean.FALSE);

            @Override public J.ClassDeclaration visitClassDeclaration(J.ClassDeclaration cd, ExecutionContext ctx) {
                boolean extendsWsca = cd.getExtends() != null
                        && TypeUtils.isOfClassType(cd.getExtends().getType(), WSCA_FQN);
                classExtendsWsca.set(extendsWsca);
                J.ClassDeclaration c = super.visitClassDeclaration(cd, ctx);
                if (extendsWsca) {
                    c = c.withExtends(null);
                    maybeRemoveImport(WSCA_FQN);
                    maybeAddImport(SECURITY_FILTER_CHAIN_FQN);
                    maybeAddImport(BEAN_FQN);
                }
                classExtendsWsca.remove();
                return c;
            }

            @Override public J.MethodDeclaration visitMethodDeclaration(J.MethodDeclaration md, ExecutionContext ctx) {
                J.MethodDeclaration m = super.visitMethodDeclaration(md, ctx);
                if (!classExtendsWsca.get()) return m;

                String name = m.getSimpleName();

                // 1. configure(HttpSecurity) → @Bean SecurityFilterChain securityFilterChain(HttpSecurity)
                if ("configure".equals(name) && hasSingleHttpSecurityParam(m)) {
                    String paramName = paramName(m);
                    // 1a. Template-based mutations FIRST (they rely on cursor's original AST).
                    m = addBeanAnnotation(m);
                    m = appendReturnBuild(m, paramName);
                    // 1b. Now in-memory AST mutations.
                    m = stripOverride(m);
                    m = m.withName(m.getName().withSimpleName("securityFilterChain"));
                    m = m.withReturnTypeExpression(
                            TypeTree.build("SecurityFilterChain")
                                    .withType(JavaType.ShallowClass.build(SECURITY_FILTER_CHAIN_FQN))
                                    .withPrefix(m.getReturnTypeExpression() == null
                                            ? org.openrewrite.java.tree.Space.EMPTY
                                            : m.getReturnTypeExpression().getPrefix())
                    );
                    m = makePublic(m);
                    return m;
                }

                // 2. authenticationManagerBean() / userDetailsServiceBean()
                //    super-delegating override → delete (operator re-adds if needed)
                if (("authenticationManagerBean".equals(name) || "userDetailsServiceBean".equals(name))
                        && delegatesToSuper(m)) {
                    return null;  // drop the method
                }

                // 3. Other configure() overloads (AuthenticationManagerBuilder / WebSecurity):
                //    strip @Override (no longer valid - WSCA is gone). For the
                //    AuthenticationManagerBuilder overload, also add @Autowired so
                //    Spring still calls it.
                if ("configure".equals(name)) {
                    if (hasSingleParamOfType(m, "org.springframework.security.config.annotation.authentication.builders.AuthenticationManagerBuilder")) {
                        // Template-based first (operates on cursor's original AST),
                        // then in-memory mutations.
                        m = ensureAutowired(m);
                        m = stripOverride(m);
                        return m;
                    }
                    if (hasSingleParamOfType(m, "org.springframework.security.config.annotation.web.builders.WebSecurity")) {
                        m = stripOverride(m);
                        m = scrubSuperCalls(m, "configure");
                        return m;
                    }
                }

                // 4. userDetailsService() — keep as @Bean (already in source typically), strip
                //    @Override (parent class gone), neutralize super.userDetailsService() body calls.
                if ("userDetailsService".equals(name) && m.getParameters().size() <= 1) {
                    m = stripOverride(m);
                    m = scrubSuperCalls(m, "userDetailsService");
                    return m;
                }

                return m;
            }

            /**
             * Rewrite `super.<methodName>(...)` calls inside the method body to
             * either: drop the statement (if void context), or replace with `null`
             * (if value-returning context). Conservative: only rewrites the
             * exact-match method name; leaves other super.* calls intact.
             */
            private J.MethodDeclaration scrubSuperCalls(J.MethodDeclaration m, String methodName) {
                if (m.getBody() == null) return m;
                org.openrewrite.java.JavaIsoVisitor<ExecutionContext> scrubber =
                    new org.openrewrite.java.JavaIsoVisitor<ExecutionContext>() {
                        @Override
                        public J.Return visitReturn(J.Return r, ExecutionContext ctx) {
                            J.Return rr = super.visitReturn(r, ctx);
                            if (rr.getExpression() instanceof J.MethodInvocation) {
                                J.MethodInvocation mi = (J.MethodInvocation) rr.getExpression();
                                if (mi.getSelect() instanceof J.Identifier
                                        && "super".equals(((J.Identifier) mi.getSelect()).getSimpleName())
                                        && methodName.equals(mi.getSimpleName())) {
                                    // Replace `return super.X(...)` with `return null;`
                                    return rr.withExpression(
                                            new J.Literal(org.openrewrite.Tree.randomId(),
                                                    org.openrewrite.java.tree.Space.SINGLE_SPACE,
                                                    org.openrewrite.marker.Markers.EMPTY,
                                                    null, "null",
                                                    null, org.openrewrite.java.tree.JavaType.Primitive.Null));
                                }
                            }
                            return rr;
                        }

                        @Override
                        public J.Block visitBlock(J.Block b, ExecutionContext ctx) {
                            J.Block bb = super.visitBlock(b, ctx);
                            // Drop bare `super.<methodName>(...);` expression-statements.
                            java.util.List<org.openrewrite.java.tree.Statement> kept = new java.util.ArrayList<>();
                            for (org.openrewrite.java.tree.Statement s : bb.getStatements()) {
                                if (s instanceof org.openrewrite.java.tree.J.MethodInvocation) {
                                    J.MethodInvocation mi = (J.MethodInvocation) s;
                                    if (mi.getSelect() instanceof J.Identifier
                                            && "super".equals(((J.Identifier) mi.getSelect()).getSimpleName())
                                            && methodName.equals(mi.getSimpleName())) {
                                        continue;  // drop
                                    }
                                }
                                kept.add(s);
                            }
                            return bb.withStatements(kept);
                        }
                    };
                return (J.MethodDeclaration) scrubber.visit(m, null, getCursor().getParentOrThrow());
            }

            // ───── helpers ─────────────────────────────────────────────────

            private boolean hasSingleHttpSecurityParam(J.MethodDeclaration m) {
                return hasSingleParamOfType(m, HTTP_SECURITY_FQN);
            }

            private boolean hasSingleParamOfType(J.MethodDeclaration m, String fqn) {
                if (m.getParameters().size() != 1) return false;
                J p = m.getParameters().get(0);
                if (!(p instanceof J.VariableDeclarations)) return false;
                return TypeUtils.isOfClassType(((J.VariableDeclarations) p).getTypeAsFullyQualified(), fqn);
            }

            private J.MethodDeclaration ensureAutowired(J.MethodDeclaration m) {
                for (J.Annotation a : m.getLeadingAnnotations()) {
                    if ("Autowired".equals(a.getSimpleName())) return m;
                }
                JavaTemplate tpl = JavaTemplate.builder("@org.springframework.beans.factory.annotation.Autowired").build();
                return tpl.apply(getCursor(), m.getCoordinates().addAnnotation(Comparator.comparing(J.Annotation::getSimpleName)));
            }

            private String paramName(J.MethodDeclaration m) {
                J p = m.getParameters().get(0);
                if (p instanceof J.VariableDeclarations) {
                    return ((J.VariableDeclarations) p).getVariables().get(0).getSimpleName();
                }
                return "http";
            }

            private boolean delegatesToSuper(J.MethodDeclaration m) {
                if (m.getBody() == null) return false;
                String src = m.getBody().toString();
                return src.contains("super.authenticationManagerBean")
                    || src.contains("super.userDetailsServiceBean");
            }

            private J.MethodDeclaration stripOverride(J.MethodDeclaration m) {
                List<J.Annotation> kept = new ArrayList<>();
                for (J.Annotation a : m.getLeadingAnnotations()) {
                    if ("Override".equals(a.getSimpleName())) continue;
                    kept.add(a);
                }
                return m.withLeadingAnnotations(kept);
            }

            private J.MethodDeclaration addBeanAnnotation(J.MethodDeclaration m) {
                for (J.Annotation a : m.getLeadingAnnotations()) {
                    if (TypeUtils.isOfClassType(a.getType(), BEAN_FQN)) return m;
                }
                JavaTemplate tpl = JavaTemplate.builder("@org.springframework.context.annotation.Bean").build();
                return tpl.apply(getCursor(), m.getCoordinates().addAnnotation(Comparator.comparing(J.Annotation::getSimpleName)));
            }

            private J.MethodDeclaration makePublic(J.MethodDeclaration m) {
                List<J.Modifier> mods = new ArrayList<>();
                boolean sawPublic = false;
                org.openrewrite.java.tree.Space firstPrefix = null;
                for (J.Modifier mod : m.getModifiers()) {
                    if (firstPrefix == null) firstPrefix = mod.getPrefix();
                    if (mod.getType() == J.Modifier.Type.Protected) continue;
                    if (mod.getType() == J.Modifier.Type.Private) continue;
                    if (mod.getType() == J.Modifier.Type.Public) sawPublic = true;
                    mods.add(mod);
                }
                if (!sawPublic) {
                    J.Modifier pub = new J.Modifier(
                            org.openrewrite.Tree.randomId(),
                            firstPrefix == null ? org.openrewrite.java.tree.Space.EMPTY : firstPrefix,
                            org.openrewrite.marker.Markers.EMPTY,
                            null,
                            J.Modifier.Type.Public,
                            java.util.Collections.emptyList()
                    );
                    mods.add(0, pub);
                    // Shift subsequent modifiers to have leading space
                    for (int i = 1; i < mods.size(); i++) {
                        J.Modifier other = mods.get(i);
                        if (other.getPrefix().getWhitespace().isEmpty()) {
                            mods.set(i, other.withPrefix(org.openrewrite.java.tree.Space.format(" ")));
                        }
                    }
                }
                return m.withModifiers(mods);
            }

            private J.MethodDeclaration appendReturnBuild(J.MethodDeclaration m, String paramName) {
                if (m.getBody() == null) return m;
                JavaTemplate tpl = JavaTemplate.builder("return " + paramName + ".build();").build();
                return tpl.apply(updateCursor(m), m.getBody().getCoordinates().lastStatement());
            }
        });
    }
}
