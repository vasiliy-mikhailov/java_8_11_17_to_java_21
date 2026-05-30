package com.example.springbootproject5.aop;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
@Aspect
public class PerformanceAspect {

    private static final Logger LOGGER = LoggerFactory.getLogger(LoggingAspect.class);

    // return type, className.method(args)
    @Around("execution(* com.example.springbootproject5.service.JobService.*(..))")
    public Object logService(ProceedingJoinPoint jp) throws Throwable {
        LOGGER.info("Measuring time...");
        long start = System.currentTimeMillis();
        // Execute method here
        Object obj = jp.proceed();

        long end = System.currentTimeMillis();
        LOGGER.info("The method " + jp.getSignature().getName() + " took: " + (end - start) + " milis");

        return obj;
    }
}
