package tech.mikhailov.bump_java_version_recipes;

import lombok.EqualsAndHashCode;
import lombok.Value;
import org.openrewrite.ExecutionContext;
import org.openrewrite.Preconditions;
import org.openrewrite.Recipe;
import org.openrewrite.TreeVisitor;
import org.openrewrite.java.JavaIsoVisitor;
import org.openrewrite.java.MethodMatcher;
import org.openrewrite.java.search.UsesType;
import org.openrewrite.java.tree.J;
import org.openrewrite.java.tree.JavaType;
import org.openrewrite.java.tree.Statement;
import org.openrewrite.java.tree.TypeTree;
import org.openrewrite.java.tree.TypeUtils;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Spring 6 changed {@code ResponseEntity.getStatusCode()} to return
 * {@code HttpStatusCode} (superinterface) instead of {@code HttpStatus}.
 * Code that assigned the result into an {@code HttpStatus} local no longer
 * compiles. This recipe widens such local variable declarations to
 * {@code HttpStatusCode}.
 *
 * <p>Detection strategy (works whether the resolved classpath is Spring 5
 * or Spring 6): walk each method, find {@code HttpStatus} local
 * declarations whose name is later assigned (or initialized) by an
 * invocation of {@code .getStatusCode()} on a {@code ResponseEntity}, and
 * widen the declared type.
 */
@Value
@EqualsAndHashCode(callSuper = false)
public class WidenHttpStatusToHttpStatusCode extends Recipe {

    private static final String HTTP_STATUS_FQN = "org.springframework.http.HttpStatus";
    private static final String HTTP_STATUS_CODE_FQN = "org.springframework.http.HttpStatusCode";

    private static final MethodMatcher GET_STATUS_CODE_TYPED =
            new MethodMatcher("org.springframework.http.ResponseEntity getStatusCode()");

    @Override public String getDisplayName() {
        return "Widen `HttpStatus` locals fed by `ResponseEntity.getStatusCode()` to `HttpStatusCode`";
    }

    @Override public String getDescription() {
        return "Spring 6 made `ResponseEntity.getStatusCode()` return `HttpStatusCode` " +
               "(superinterface) instead of `HttpStatus`. Variable declarations like " +
               "`HttpStatus s = re.getStatusCode();` no longer compile. This recipe widens " +
               "the declared type to `HttpStatusCode` (and adjusts imports). Does not rewrite " +
               "downstream `.getReasonPhrase()` / `.series()` calls.";
    }

    @Override public TreeVisitor<?, ExecutionContext> getVisitor() {
        return Preconditions.check(
                Preconditions.and(
                        new UsesType<>(HTTP_STATUS_FQN, true),
                        new UsesType<>("org.springframework.http.ResponseEntity", true)
                ),
                new JavaIsoVisitor<ExecutionContext>() {
                    @Override
                    public J.MethodDeclaration visitMethodDeclaration(J.MethodDeclaration md, ExecutionContext ctx) {
                        J.MethodDeclaration m = super.visitMethodDeclaration(md, ctx);
                        if (m.getBody() == null) return m;
                        // Collect names that are assigned from <something>.getStatusCode() anywhere in the method body
                        Set<String> namesAssignedFromGetStatusCode = new HashSet<>();
                        new JavaIsoVisitor<Set<String>>() {
                            @Override
                            public J.Assignment visitAssignment(J.Assignment a, Set<String> acc) {
                                J.Assignment ax = super.visitAssignment(a, acc);
                                if (ax.getVariable() instanceof J.Identifier && isGetStatusCodeCall(ax.getAssignment())) {
                                    acc.add(((J.Identifier) ax.getVariable()).getSimpleName());
                                }
                                return ax;
                            }
                            @Override
                            public J.VariableDeclarations visitVariableDeclarations(J.VariableDeclarations v, Set<String> acc) {
                                J.VariableDeclarations vx = super.visitVariableDeclarations(v, acc);
                                for (J.VariableDeclarations.NamedVariable nv : vx.getVariables()) {
                                    if (isGetStatusCodeCall(nv.getInitializer())) {
                                        acc.add(nv.getSimpleName());
                                    }
                                }
                                return vx;
                            }
                        }.visit(m.getBody(), namesAssignedFromGetStatusCode);

                        if (namesAssignedFromGetStatusCode.isEmpty()) {
                            return m;
                        }

                        // Now walk the body and widen matching HttpStatus declarations
                        boolean[] changed = {false};
                        J.Block newBody = (J.Block) new JavaIsoVisitor<ExecutionContext>() {
                            @Override
                            public J.VariableDeclarations visitVariableDeclarations(J.VariableDeclarations v, ExecutionContext c) {
                                J.VariableDeclarations vx = super.visitVariableDeclarations(v, c);
                                if (!TypeUtils.isOfClassType(vx.getTypeAsFullyQualified(), HTTP_STATUS_FQN)) {
                                    return vx;
                                }
                                boolean anyMatch = vx.getVariables().stream()
                                        .anyMatch(nv -> namesAssignedFromGetStatusCode.contains(nv.getSimpleName()));
                                if (!anyMatch) return vx;
                                // Widen type
                                TypeTree newType = TypeTree.build("HttpStatusCode")
                                        .withType(JavaType.ShallowClass.build(HTTP_STATUS_CODE_FQN));
                                if (vx.getTypeExpression() != null) {
                                    newType = newType.withPrefix(vx.getTypeExpression().getPrefix());
                                }
                                vx = vx.withTypeExpression(newType);
                                List<J.VariableDeclarations.NamedVariable> newVars = new ArrayList<>();
                                JavaType statusCodeType = JavaType.ShallowClass.build(HTTP_STATUS_CODE_FQN);
                                for (J.VariableDeclarations.NamedVariable nv : vx.getVariables()) {
                                    JavaType.Variable oldVarType = nv.getName().getFieldType();
                                    if (oldVarType != null) {
                                        JavaType.Variable newVarType = oldVarType.withType(statusCodeType);
                                        nv = nv.withName(nv.getName().withFieldType(newVarType).withType(statusCodeType));
                                    } else {
                                        nv = nv.withName(nv.getName().withType(statusCodeType));
                                    }
                                    newVars.add(nv);
                                }
                                vx = vx.withVariables(newVars);
                                changed[0] = true;
                                return vx;
                            }
                        }.visit(m.getBody(), ctx);

                        if (changed[0]) {
                            m = m.withBody(newBody);
                            maybeAddImport(HTTP_STATUS_CODE_FQN);
                            // Only remove HttpStatus import if no remaining usage in this file -
                            // OpenRewrite handles that conservatively via maybeRemoveImport.
                            maybeRemoveImport(HTTP_STATUS_FQN);
                        }
                        return m;
                    }

                    private boolean isGetStatusCodeCall(org.openrewrite.java.tree.Expression e) {
                        if (!(e instanceof J.MethodInvocation)) return false;
                        J.MethodInvocation mi = (J.MethodInvocation) e;
                        if (GET_STATUS_CODE_TYPED.matches(mi)) return true;
                        // Fallback: name match + select is ResponseEntity-typed
                        if (!"getStatusCode".equals(mi.getSimpleName())) return false;
                        if (mi.getSelect() == null) return false;
                        JavaType.FullyQualified selectT = TypeUtils.asFullyQualified(mi.getSelect().getType());
                        if (selectT != null
                                && selectT.getFullyQualifiedName().startsWith("org.springframework.http.ResponseEntity")) {
                            return true;
                        }
                        // Last-resort: untyped match by name + select looks like a local var
                        return mi.getSelect() instanceof J.Identifier;
                    }
                });
    }
}
