package com.example.springbootproject3;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HomeController {

    @RequestMapping("/")
    public String home() {
        System.out.println("home called");
        return "hello world. Home";
    }

    @RequestMapping("/sum")
    public String sum(@RequestParam String a, @RequestParam String b) {
        Integer result = Integer.parseInt(a) + Integer.parseInt(b);
        String returnString = a + " + " + b + " is: " + result.toString();
        System.out.println(returnString);
        return returnString;
    }
}
