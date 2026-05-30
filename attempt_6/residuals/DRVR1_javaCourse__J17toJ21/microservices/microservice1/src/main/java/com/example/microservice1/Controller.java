package com.example.microservice1;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

//http://localhost:8080/swagger-ui/index.html
@RestController
public class Controller {

    @GetMapping("/")
    public String helloWorld() {
        return "service 1 - hello world";
    }
}
