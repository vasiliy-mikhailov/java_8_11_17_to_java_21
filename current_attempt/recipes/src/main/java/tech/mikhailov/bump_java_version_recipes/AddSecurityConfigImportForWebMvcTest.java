package tech.mikhailov.bump_java_version_recipes;

import lombok.EqualsAndHashCode;
import lombok.Value;
import org.openrewrite.ExecutionContext;
import org.openrewrite.ScanningRecipe;
import org.openrewrite.Tree;
import org.openrewrite.TreeVisitor;
import org.openrewrite.java.AnnotationMatcher;
import org.openrewrite.java.JavaIsoVisitor;
import org.openrewrite.java.JavaParser;
import org.openrewrite.java.JavaTemplate;
import org.openrewrite.java.tree.J;
import org.openrewrite.java.tree.JavaType;

import java.util.Comparator;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Adds @Import({SecurityConfig.class}) to any class annotated with @WebMvcTest,
 * where SecurityConfig is the project's own class annotated with @EnableWebSecurity.
 *
 * The SecurityConfig is discovered by classpath scan in the scanning phase,
 * so this recipe is project-name- and package-agnostic.
 */
@Value
@EqualsAndHashCode(callSuper = false)
public class AddSecurityConfigImportForWebMvcTest
        extends ScanningRecipe<AtomicReference<String>> {

    @Override
    public String getDisplayName() {
        return "Add @Import for the project's SecurityConfig to every @WebMvcTest test slice";
    }

    @Override
    public String getDescription() {
        return "Spring Boot 3 @WebMvcTest slices do not pick up the project's main " +
               "SecurityConfig by default. When the project has a @Configuration class " +
               "annotated with @EnableWebSecurity, this recipe @Import-s it into every " +
               "@WebMvcTest class so the test slice gets the project's real security " +
               "filter chain instead of the auto-configured default.";
    }

    @Override
    public AtomicReference<String> getInitialValue(ExecutionContext ctx) {
        return new AtomicReference<>(null);
    }

    @Override
    public TreeVisitor<?, ExecutionContext> getScanner(AtomicReference<String> acc) {
        final AnnotationMatcher enableWebSecurity =
                new AnnotationMatcher("@org.springframework.security.config.annotation.web.configuration.EnableWebSecurity");
        return new JavaIsoVisitor<ExecutionContext>() {
            @Override
            public J.ClassDeclaration visitClassDeclaration(J.ClassDeclaration cd, ExecutionContext ctx) {
                if (acc.get() != null) return cd;
                boolean hasEnable = cd.getLeadingAnnotations().stream().anyMatch(enableWebSecurity::matches);
                if (!hasEnable) return cd;
                JavaType.FullyQualified fq = cd.getType();
                if (fq == null) return cd;
                acc.set(fq.getFullyQualifiedName());
                return cd;
            }
        };
    }

    @Override
    public TreeVisitor<?, ExecutionContext> getVisitor(AtomicReference<String> acc) {
        return new JavaIsoVisitor<ExecutionContext>() {
            final AnnotationMatcher webMvcTest =
                    new AnnotationMatcher("@org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest");
            final AnnotationMatcher importAnno =
                    new AnnotationMatcher("@org.springframework.context.annotation.Import");

            @Override
            public J.ClassDeclaration visitClassDeclaration(J.ClassDeclaration cd, ExecutionContext ctx) {
                J.ClassDeclaration c = super.visitClassDeclaration(cd, ctx);
                String securityConfigFqn = acc.get();
                if (securityConfigFqn == null) return c;
                boolean hasWebMvc = c.getLeadingAnnotations().stream().anyMatch(webMvcTest::matches);
                boolean alreadyImported = c.getLeadingAnnotations().stream().anyMatch(importAnno::matches);
                if (!hasWebMvc || alreadyImported) return c;

                JavaTemplate tpl = JavaTemplate.builder(
                        "@org.springframework.context.annotation.Import(" + securityConfigFqn + ".class)")
                        .build();
                maybeAddImport("org.springframework.context.annotation.Import");
                maybeAddImport(securityConfigFqn);
                return tpl.apply(getCursor(), c.getCoordinates().addAnnotation(Comparator.comparing(J.Annotation::getSimpleName)));
            }
        };
    }
}
