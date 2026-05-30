package com.example.springbootproject5.aop;

import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
@Aspect
public class LoggingAspect {

    private static final Logger LOGGER = LoggerFactory.getLogger(LoggingAspect.class);

    // return type, className.method(args)
    @Before("execution(* com.example.springbootproject5.service.JobService.*(..))")
    public void logService() {
        LOGGER.info("Service method called");
    }
}
